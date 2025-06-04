#!/usr/bin/env python3
import argparse
import contextlib
import dataclasses
import logging
import os
import shutil
import subprocess
import sys
import time
from typing import Callable


def run_command[**P](command: str, command_args: list[str],
                     runner: Callable[P, subprocess.CompletedProcess[str]] = subprocess.run, **kwargs: P.kwargs) -> str:
    full_command = [command] + command_args
    try:
        result = runner(args=full_command, text=True, stdout=subprocess.PIPE, **kwargs)
        result.check_returncode()  # Explicitly check return code
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error executing {command} command: {' '.join(full_command)}")
        print(f"Stdout: {e.stdout}")  # It's useful to see stdout on error too
        print(f"Stderr: {e.stderr}")
        sys.exit(e.returncode)  # Exit with the command's return code
    except FileNotFoundError:
        print(f"Error: '{command}' command not found. Please ensure {command} is installed and in your PATH.")
        sys.exit(1)


def run_kubectl_command(command_args: list[str]) -> str:
    """
    Runs a kubectl command and returns its stdout.
    Exits if the command fails.
    """
    return run_command("kubectl", command_args)


def sanitize_filename(name: str):
    """Sanitizes a string to be a valid filename."""
    return ''.join(c if c.isalnum() or c in ['-', '_', '.'] else '_' for c in name)


def collect_kubernetes_logs_with_kubectl_subprocess(logs_dir="ci-logs", log_since="10m",
                                                    namespace_label="collect_logs=true"):
    """
    Collects Kubernetes pod logs into structured directories using kubectl via subprocess.

    Args:
        logs_dir (str): Base directory to save logs.
        log_since (str): Duration for logs to collect (e.g., "10m", "1h").
        namespace_label (str): Label selector for namespaces (e.g., "collect_logs=true").
    """
    os.makedirs(logs_dir, exist_ok=True)
    print(f"Starting log collection into '{logs_dir}'...")

    # Get namespaces with the specified label using kubectl
    namespaces_output = run_kubectl_command([
        "get", "namespaces",
        "-l", namespace_label,
        "-o", "jsonpath={.items[*].metadata.name}"
    ])

    target_namespaces = namespaces_output.split() if namespaces_output else []

    if not target_namespaces:
        print(f"No namespaces found with label '{namespace_label}'. Collecting all namespaces.")
        target_namespaces = run_kubectl_command([
            "get", "namespaces",
            "-o", "jsonpath={.items[*].metadata.name}\n"
        ])

    stern_processes: list[subprocess.Popen] = []  # To keep track of background stern processes

    for namespace in target_namespaces.split():
        print(f"\nCollecting logs for namespace: {namespace}")
        namespace_dir = os.path.join(logs_dir, sanitize_filename(namespace))
        os.makedirs(namespace_dir, exist_ok=True)

        # Get pod names in the current namespace using kubectl
        pods_output = run_kubectl_command([
            "get", "pods",
            "-n", namespace,
            "-o", "jsonpath={.items[*].metadata.name}"
        ])

        target_pods = pods_output.split() if pods_output else []

        if not target_pods:
            print(f"  No pods found in namespace {namespace}. Skipping.")
            continue

        for pod_name in target_pods:
            print(f"    - Collecting logs for pod: {pod_name}")
            sanitized_pod_name = sanitize_filename(pod_name)
            log_file_path = os.path.join(namespace_dir, f"{sanitized_pod_name}.log")

            # Construct the stern command
            stern_command = [
                "stern",
                pod_name,
                "-n", namespace,
                "--since", log_since,
                "--timestamps",
                "--output", "raw",
                "--no-follow",
            ]

            try:
                # Start stern as a background process and redirect output
                with open(log_file_path, "w") as outfile:
                    process = subprocess.Popen(stern_command, stdout=outfile, stderr=subprocess.STDOUT)
                    stern_processes.append(process)
            except FileNotFoundError:
                print("    Error: 'stern' command not found. Stern must be installed and in your PATH.")
                sys.exit(1)  # Consider if exiting immediately is desired for one missing stern
            except Exception as e:
                print(f"    Error starting stern for {pod_name} in namespace {namespace}: {e}")

    if stern_processes:  # Only wait if stern processes were started
        print("\nWaiting for all stern processes to complete...")
        for proc in stern_processes:
            proc.wait()  # Wait for each background process to finish
    else:
        print("\nNo stern processes were started.")

    returncodes = [proc.returncode for proc in stern_processes]
    if any(rc != 0 for rc in returncodes):
        cnt = sum(rc != 0 for rc in returncodes)
        total = len(returncodes)
        print(f"\nWarning: {cnt}/{total} stern processes finished with non-zero exit codes.")

    print(f"Log collection complete. Logs are available in the '{logs_dir}' directory.")

    if "GITHUB_ACTIONS" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "at") as f:
            print(f'logs_dir={logs_dir}', file=f)
    else:
        logging.info("Not running on Github Actions, won't produce GITHUB_OUTPUT")


def check_command_exists(command: str) -> bool:
    """Checks if a given command is available in the system's PATH."""
    return shutil.which(command) is not None


def install_stern(version="1.32.0", arch="linux_amd64", path="/usr/local/bin", retries=3, delay=5):
    """Downloads (curl with retries), extracts (tar), and installs stern."""
    archive = f"stern_{version}_{arch}.tar.gz"
    url = f"https://github.com/stern/stern/releases/download/v{version}/{archive}"

    # Download with retries
    for attempt in range(retries):
        try:
            if os.path.exists(archive): os.remove(archive)  # Clean up partial download
            print(f"Attempt {attempt + 1}/{retries}: Downloading {archive} from {url}...")
            subprocess.run(["curl", "--location", "--remote-name", url], check=True, capture_output=True)
            break
        except subprocess.CalledProcessError as e:
            print(f"Download failed: {e.stderr.decode().strip()}", file=sys.stderr)
            if attempt == retries - 1: sys.exit(1)  # Exhausted retries
            time.sleep(delay)
        except FileNotFoundError:
            sys.exit("Error: 'curl' not found. Please install it.")
        except Exception as e:
            print(f"Unexpected download error: {e}", file=sys.stderr);
            sys.exit(1)
    else:
        sys.exit("Failed to download after all attempts.")  # Fallback if loop finishes without break

    # Extract and Install
    try:
        subprocess.run(["tar", "--extract", "--gzip", "--file", archive], check=True, capture_output=True)
        subprocess.run(["sudo", "mv", "--target-directory", path, "stern"], check=True, capture_output=True)
        subprocess.run(["sudo", "chmod", "--recursive", "+x", os.path.join(path, "stern")], check=True,
                       capture_output=True)
        print(f"Stern v{version} installed successfully!")
    except FileNotFoundError as e:
        sys.exit(f"Error: Command not found ({e}). Ensure tar/sudo/mv/chmod are installed.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"Install failed: {e.stderr.decode().strip()}")
    finally:
        if os.path.exists(archive): os.remove(archive)
        if os.path.exists("stern"): os.remove("stern")


@contextlib.contextmanager
def gha_log_group(title: str) -> None:
    """Prints the starting and ending magic strings for GitHub Actions line group in log."""
    print(f"::group::{title}", file=sys.stdout)
    sys.stdout.flush()
    try:
        yield
    finally:
        print("::endgroup::", file=sys.stdout)
        sys.stdout.flush()


def print_notebook_logs():
    """
    Collects logs from all notebooks in the current directory and prints them.
    """
    print("\nCollecting logs from notebooks:")
    subprocess.run(
        '''stern --selector "app in (notebook-controller, odh-notebook-controller)" -n redhat-ods-applications --no-follow --tail -1 --timestamps --color always | sort -k3''',
        shell=True, check=True)


# Define a dataclass to hold the parsed arguments
@dataclasses.dataclass()
class ScriptArgs:
    """
    Dataclass to hold command-line arguments for log collection.
    """
    logs_dir: str = dataclasses.field(
        default="ci-kubernetes-logs",
        metadata={"help": "Base directory to save collected logs."}
    )
    since: str = dataclasses.field(
        default="10m",
        metadata={"help": "Duration for logs to collect (e.g., '5s', '2m', '1h')."}
    )
    namespace_label: str = dataclasses.field(
        default="collect_logs=true",
        metadata={"help": "Label selector for namespaces to collect logs from (e.g., 'env=prod')."}
    )
    # The dataclass_fields property is no longer needed with dataclasses.fields()


def main():
    parser = argparse.ArgumentParser(
        description="Collects Kubernetes pod logs from labeled namespaces into structured directories."
    )

    # Add arguments to the parser based on the dataclass fields
    # We iterate through the fields of ScriptArgs to automatically add them
    for field_obj in dataclasses.fields(ScriptArgs):
        parser.add_argument(
            f"--{field_obj.name.replace('_', '-')}",  # Convert snake_case to kebab-case for CLI
            type=field_obj.type,
            default=field_obj.default,
            help=field_obj.metadata.get("help", "") + f" (default: {field_obj.default})"
        )

    # parser.parse_args() returns a Namespace object.
    # For type safety and to use ScriptArgs features (if any were added later),
    # it's better to instantiate ScriptArgs.
    parsed_namespace = parser.parse_args()
    args = ScriptArgs(**vars(parsed_namespace))  # Instantiate ScriptArgs

    if not check_command_exists("stern"):
        install_stern()

    with gha_log_group("collecting logs to files"):
        collect_kubernetes_logs_with_kubectl_subprocess(
            logs_dir=args.logs_dir,
            log_since=args.since,
            namespace_label=args.namespace_label
        )

    with gha_log_group("nbc controller logs"):
        print_notebook_logs()


if __name__ == "__main__":
    main()
