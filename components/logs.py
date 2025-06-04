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
from typing import Callable, Dict, Any, List

"""
TODO:
* kubectl describe
* kubectl logs --previous
* must-gather
"""

def run_command[**P](
        command: str, command_args: list[str],
        runner: Callable[P, subprocess.CompletedProcess[str]] = subprocess.run,
        check: bool = False,
        **kwargs: P.kwargs
) -> str:
    """
    Runs a command using subprocess.run, forwarding keyword arguments.

    Args:
        command: The base command (e.g., "kubectl").
        command_args: A list of arguments for the command.
        runner: The function to use for running the command (defaults to subprocess.run).
        **kwargs: Keyword arguments to pass directly to the runner function.
                  These should match the valid keyword arguments for the runner (e.g., subprocess.run).

    Returns:
        The standard output of the command as a string, stripped of leading/trailing whitespace.

    Exits:
        If the command fails (non-zero exit code) or the command is not found.
    """
    full_command = [command] + command_args
    try:
        # Pass kwargs directly to the runner
        # Ensure text=True and stdout=subprocess.PIPE are defaults unless overridden
        merged_kwargs = {'text': True, 'stdout': subprocess.PIPE, **kwargs}

        result = runner(args=full_command, **merged_kwargs)
        result.check_returncode()  # Explicitly check return code
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {' '.join(full_command)}")
        print(f"Return code: {e.returncode}")
        # It's useful to see stdout/stderr on error
        if e.stdout:
            print(f"Stdout:\n{e.stdout.strip()}")
        if e.stderr:
            print(f"Stderr:\n{e.stderr.strip()}")
        if check:
            sys.exit(e.returncode)  # Exit with the command's return code
        return e.stdout.strip()
    except FileNotFoundError:
        print(f"Error: '{command}' command not found. Please ensure {command} is installed and in your PATH.")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred while running command {' '.join(full_command)}: {e}")
        sys.exit(1)


def run_kubectl_command(command_args: list[str], **kwargs: Dict[str, Any]) -> str:
    """
    Runs a kubectl command and returns its stdout.
    Exits if the command fails.
    Forwards kwargs to run_command (and thus subprocess.run).
    """
    return run_command("kubectl", command_args, **kwargs)


def sanitize_filename(name: str):
    """Sanitizes a string to be a valid filename."""
    return ''.join(c if c.isalnum() or c in ['-', '_', '.'] else '_' for c in name)


def get_api_group_from_apiversion(api_version: str) -> str:
    """Extracts the API group from an apiVersion string."""
    if '/' not in api_version:
        # Core API group (e.g., "v1")
        return "core"
    return api_version.split('/')[0]


@dataclasses.dataclass
class Resource:
    """
    Represents a Kubernetes resource type.
    """
    api_version: str
    kind: str

def discover_api_resources() -> tuple[list[Resource], list[Resource]]:
    """
    Discovers available API resources using 'kubectl api-resources'.

    Returns:
        A tuple containing two lists: (cluster_scoped_types, namespaced_types).
    """
    print("Discovering API resources...")
    output = run_kubectl_command(["api-resources", "--no-headers=true", "-o", "wide"])

    cluster_scoped_types = []
    namespaced_types = []

    # Parse the output (assuming standard wide format: NAME SHORTNAMES APIVERSIONS NAMESPACED KIND)
    # We need the first column (NAME) and the fourth column (NAMESPACED)
    for line in output.splitlines():
        if not line.strip():
            continue
        # Split by whitespace, handle potential multiple spaces
        parts = line.split()
        if len(parts) < 5:  # Expect at least 5 columns in wide output
            print(f"Skipping unexpected line format from api-resources: {line}", file=sys.stderr)
            continue

        resource_name = parts[0]
        api_version = parts[2]
        is_namespaced_str = parts[3].lower()  # 'true' or 'false'

        # Skip known problematic or overly verbose types if necessary
        # Example: "events.events.k8s.io" might be redundant if "events" is collected
        # Or skip specific CRDs you don't need
        # if resource_name in ["events.events.k8s.io"]:
        #     continue

        resource = Resource(api_version=api_version, kind=resource_name)
        if is_namespaced_str == 'true':
            namespaced_types.append(resource)
        elif is_namespaced_str == 'false':
            cluster_scoped_types.append(resource)
        # else: unexpected value in NAMESPACED column

    print(
        f"Discovered {len(cluster_scoped_types)} cluster-scoped and {len(namespaced_types)} namespaced resource types.")
    return cluster_scoped_types, namespaced_types


def collect_kubernetes_resources(output_dir="ci-debug-bundle"):
    """
    Collects Kubernetes resource definitions (YAML) from the cluster.

    Args:
        output_dir (str): Base directory to save resources.
    """
    print(f"Starting resource collection into '{output_dir}'...")

    cluster_scoped_dir = os.path.join(output_dir, "cluster-scoped-resources")
    namespaces_dir = os.path.join(output_dir, "namespaces")

    os.makedirs(cluster_scoped_dir, exist_ok=True)
    os.makedirs(namespaces_dir, exist_ok=True)

    # --- Discover Resource Types Dynamically ---
    cluster_scoped_types, namespaced_types = discover_api_resources()

    # --- Collect Cluster-Scoped Resources ---
    print("\nCollecting cluster-scoped resources...")
    for resource_type in cluster_scoped_types:
        print(f"  Collecting {resource_type.kind}...")
        try:
            # Use --ignore-not-found to skip types that don't exist in the cluster
            # Use --chunk-size=0 to attempt to get all items in one go for large clusters
            output = run_kubectl_command(
                ["get", resource_type.kind, "-o", "yaml", "--ignore-not-found=true", "--chunk-size=0"])
            if not output.strip():
                # print(f"    No {resource_type} found or type does not exist.") # Can be noisy
                continue

            api_version = resource_type.api_version
            kind = resource_type.kind
            api_group = get_api_group_from_apiversion(api_version)

            # Create directory structure: cluster-scoped-resources/<api_group>/<kind>.yaml
            resource_type_dir = os.path.join(cluster_scoped_dir, sanitize_filename(api_group))
            os.makedirs(resource_type_dir, exist_ok=True)

            file_path = os.path.join(resource_type_dir, f"{sanitize_filename(kind.lower())}.yaml")
            with open(file_path, "w") as f:
                f.write(output)
            # print(f"    Saved {kind} '{name}'") # Optional: print each saved resource
        except SyntaxError | TypeError | ValueError:
            raise
        except Exception as e:
            print(f"    An unexpected error occurred collecting {resource_type}: {e}", file=sys.stderr)

    # --- Collect Namespaced Resources ---
    print("\nCollecting namespaced resources...")
    namespaces_output = run_kubectl_command([
        "get", "namespaces",
        "-o", "jsonpath={.items[*].metadata.name}"
    ])
    all_namespaces = namespaces_output.split() if namespaces_output else []

    if not all_namespaces:
        print("No namespaces found in the cluster. Skipping namespaced resource collection.")
        return

    for namespace in all_namespaces:
        print(f"  Collecting resources for namespace: {namespace}")
        namespace_output_dir = os.path.join(namespaces_dir, sanitize_filename(namespace))
        os.makedirs(namespace_output_dir, exist_ok=True)

        # Save the namespace definition itself
        try:
            # NOTE: this may fail if namespace was terminating
            ns_yaml = run_kubectl_command(["get", "namespace", namespace, "-o", "yaml"])
            with open(os.path.join(namespace_output_dir, f"{sanitize_filename(namespace)}.yaml"), "w") as f:
                f.write(ns_yaml)
        except Exception as e:
            print(f"    Error collecting namespace definition for {namespace}: {e}", file=sys.stderr)

        for resource_type in namespaced_types:
            print(f"    Collecting {resource_type.kind} in {namespace}...")  # Can be noisy
            try:
                # Use --ignore-not-found to skip types that don't exist in the namespace or cluster
                # Use --chunk-size=0 for large namespaces
                output = run_kubectl_command(
                    ["get", resource_type.kind, "-n", namespace, "-o", "yaml", "--ignore-not-found=true", "--chunk-size=0"])

                if not output.strip():
                    print(f"      No {resource_type.kind} found in {namespace}.")  # Can be noisy
                    continue

                api_version = resource_type.api_version
                kind = resource_type.kind
                api_group = get_api_group_from_apiversion(api_version)

                # Handle core resources specifically
                if api_group == "core":
                    resource_type_dir = os.path.join(namespace_output_dir, "core")
                else:
                    # Structure: namespaces/<namespace>/<api_group>/<kind>s.yaml
                    resource_type_dir = os.path.join(namespace_output_dir, sanitize_filename(api_group))

                os.makedirs(resource_type_dir, exist_ok=True)

                file_path = os.path.join(resource_type_dir, f"{sanitize_filename(kind.lower())}s.yaml")
                with open(file_path, "w") as f:
                    f.write(output)
                # print(f"      Saved {kind} '{name}' in {namespace}") # Optional: print each saved resource
            except SyntaxError | TypeError | ValueError:
                raise
            except Exception as e:
                print(f"    An unexpected error occurred collecting {resource_type} in {namespace}: {e}",
                      file=sys.stderr)

    print("\nResource collection complete.")


def collect_kubernetes_logs_with_kubectl_subprocess(logs_dir="ci-debug-bundle/logs", log_since="10m",
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
    # Use --ignore-not-found=true in case the label doesn't match any namespaces
    namespaces_output = run_kubectl_command([
        "get", "namespaces",
        "-l", namespace_label,
        "-o", "jsonpath={.items[*].metadata.name}",
        "--ignore-not-found=true"
    ]).split()

    target_namespaces = namespaces_output.split() if namespaces_output else []

    if not target_namespaces:
        print(f"No namespaces found with label '{namespace_label}'. Collecting all namespaces.")
        target_namespaces = run_kubectl_command([
            "get", "namespaces",
            "-o", "jsonpath={.items[*].metadata.name}\n"
        ]).split()

    stern_processes: list[subprocess.Popen] = []  # To keep track of background stern processes

    for namespace in target_namespaces:  # Iterate directly over the list
        print(f"\nCollecting logs for namespace: {namespace}")
        namespace_dir = os.path.join(logs_dir, sanitize_filename(namespace))
        os.makedirs(namespace_dir, exist_ok=True)

        # Get pod names in the current namespace using kubectl
        # Use --ignore-not-found=true in case there are no pods in the namespace
        pods_output = run_kubectl_command([
            "get", "pods",
            "-n", namespace,
            "-o", "jsonpath={.items[*].metadata.name}",
            "--ignore-not-found=true"
        ])

        target_pods = pods_output.split() if pods_output else []

        if not target_pods:
            print(f"  No pods found in namespace {namespace}. Skipping log collection for this namespace.")
            continue

        for pod_name in target_pods:
            # print(f"    - Collecting logs for pod: {pod_name}") # Can be noisy
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
                # Use a context manager for the file to ensure it's closed
                with open(log_file_path, "w") as outfile:
                    # Use subprocess.Popen for background process
                    process = subprocess.Popen(stern_command, stdout=outfile, stderr=subprocess.STDOUT)
                    stern_processes.append(process)
            except FileNotFoundError:
                print("    Error: 'stern' command not found. Stern must be installed and in your PATH.",
                      file=sys.stderr)
                # Exiting immediately is safer if stern is a hard requirement
                sys.exit(1)
            except Exception as e:
                print(f"    Error starting stern for {pod_name} in namespace {namespace}: {e}", file=sys.stderr)

    if stern_processes:
        print("\nWaiting for all stern processes to complete...")
        # Use wait() in a loop to catch potential issues, though wait() on Popen is blocking
        # A more advanced approach might use select or asyncio, but wait() is simpler here.
        for i, proc in enumerate(stern_processes):
            try:
                proc.wait()
                # print(f"Stern process {i+1}/{len(stern_processes)} finished.") # Optional progress
            except Exception as e:
                print(f"Error waiting for stern process {i + 1}: {e}", file=sys.stderr)

    else:
        print("\nNo stern processes were started for log collection.")

    returncodes = [proc.returncode for proc in stern_processes]
    if any(rc != 0 for rc in returncodes):
        cnt = sum(rc != 0 for rc in returncodes)
        total = len(returncodes)
        print(f"\nWarning: {cnt}/{total} stern processes finished with non-zero exit codes.", file=sys.stderr)

    print(f"Log collection complete. Logs are available in the '{logs_dir}' directory.")

    # GITHUB_OUTPUT logic remains the same
    if "GITHUB_ACTIONS" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "at") as f:
            print(f'logs_dir={logs_dir}', file=f)
    else:
        logging.info("Not running on Github Actions, won't produce GITHUB_OUTPUT for logs")


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
            if os.path.exists(archive):
                os.remove(archive)  # Clean up partial download
            print(f"Attempt {attempt + 1}/{retries}: Downloading {archive} from {url}...")
            subprocess.run([
                "curl",
                "--location",
                "--remote-name",
                # curl: You must select either --fail or --fail-with-body, not both.
                "--fail-with-body",
                "--retry", str(retries),
                "--retry-delay", str(delay),
                url
            ], check=True, capture_output=True)
            print("Download successful.")
            break  # Exit retry loop on success
        except subprocess.CalledProcessError as e:
            print(f"Download failed (Attempt {attempt + 1}/{retries}): {e.stderr.decode().strip()}", file=sys.stderr)
            if attempt == retries - 1:
                sys.exit(f"Exhausted retries. Failed to download {archive}.")
            time.sleep(delay)
        except FileNotFoundError:
            sys.exit("Error: 'curl' not found. Please install it.")
        except Exception as e:
            print(f"Unexpected download error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # This else block is reached if the loop finishes *without* a break
        # The sys.exit inside the loop handles the exhausted retries case,
        # so this might be redundant but harmless.
        sys.exit("Failed to download after all attempts (loop finished without break).")

    # Extract and Install
    try:
        print(f"Extracting {archive}...")
        subprocess.run(["tar", "--extract", "--gzip", "--file", archive], check=True, capture_output=True)
        print("Extraction successful.")

        print(f"Installing stern to {path}...")
        # Ensure target directory exists before moving
        os.makedirs(path, exist_ok=True)
        # Corrected chmod to not be recursive
        subprocess.run(["sudo", "mv", "--target-directory", path, "stern"], check=True, capture_output=True)
        subprocess.run(["sudo", "chmod", "+x", os.path.join(path, "stern")], check=True, capture_output=True)
        print(f"Stern v{version} installed successfully to {os.path.join(path, 'stern')}!")
    except FileNotFoundError as e:
        sys.exit(f"Error: Command not found during installation ({e}). Ensure tar, sudo, mv, chmod are installed.")
    except subprocess.CalledProcessError as e:
        print(f"Install failed: {e.stderr.decode().strip()}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error during installation: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Clean up downloaded archive and extracted binary from current dir
        if os.path.exists(archive):
            os.remove(archive)
        if os.path.exists("stern"):
            os.remove("stern")


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
    Collects logs from specific notebook-related pods and prints them to stdout.
    This is likely for interactive debugging rather than file collection.
    """
    print("\nCollecting logs from notebook controllers (printing to stdout):")
    subprocess.run(
        '''stern --selector "app in (notebook-controller, odh-notebook-controller)" -n redhat-ods-applications --no-follow --tail -1 --timestamps --color always | sort -k3''',
        shell=True, check=True,
    )


# Define a dataclass to hold the parsed arguments
@dataclasses.dataclass()
class ScriptArgs:
    """
    Dataclass to hold command-line arguments for log and resource collection.
    """
    output_dir: str = dataclasses.field(
        default="ci-debug-bundle",
        metadata={"help": "Base directory to save collected resources and logs."}
    )
    log_since: str = dataclasses.field(
        default="10m",
        metadata={"help": "Duration for logs to collect (e.g., '5s', '2m', '1h'). Only applies to log collection."}
    )
    log_namespace_label: str = dataclasses.field(
        default="collect_logs=true",
        metadata={"help": "Label selector for namespaces to collect logs from (e.g., 'env=prod')."}
    )


def main():
    parser = argparse.ArgumentParser(
        description="Collects Kubernetes resources and pod logs from the cluster into structured directories, similar to must-gather."
    )

    # Add arguments to the parser based on the dataclass fields
    for field_obj in dataclasses.fields(ScriptArgs):
        arg_name = field_obj.name.replace('_', '-')
        parser.add_argument(
            f"--{arg_name}",
            type=field_obj.type,
            default=field_obj.default,
            help=field_obj.metadata.get("help", "") + f" (default: {field_obj.default})"
        )

    parsed_namespace = parser.parse_args()
    args = ScriptArgs(**vars(parsed_namespace))  # Instantiate ScriptArgs

    # Check for kubectl first, as it's required for both resource and log collection
    if not check_command_exists("kubectl"):
        sys.exit("Error: 'kubectl' command not found. Please ensure kubectl is installed and in your PATH.")

    # Resource collection doesn't strictly need stern, but log collection does.
    # Install stern if not present before attempting log collection.
    stern_exists = check_command_exists("stern")
    if not stern_exists:
        print("Stern command not found. Attempting to install stern for log collection.")
        install_stern()  # This function exits on failure

    # Use the output_dir argument for both resources and logs, creating subdirectories within it.
    resource_output_dir = args.output_dir  # Resources go directly into the base output dir
    log_output_dir = os.path.join(args.output_dir, "logs")  # Logs go into a 'logs' subdirectory

    # Collect resources first
    with gha_log_group("collecting kubernetes resources"):
        collect_kubernetes_resources(output_dir=resource_output_dir)

    # Then collect logs (only if stern was found or successfully installed)
    if check_command_exists("stern"):  # Re-check in case installation failed but didn't exit
        with gha_log_group("collecting pod logs to files"):
            collect_kubernetes_logs_with_kubectl_subprocess(
                logs_dir=log_output_dir,  # Use the logs subdirectory
                log_since=args.log_since,
                namespace_label=args.log_namespace_label
            )
    else:
        print("\nSkipping log collection as stern is not available.", file=sys.stderr)

    # Print notebook logs (still prints to stdout)
    with gha_log_group("nbc controller logs (stdout)"):
        print_notebook_logs()  # This function prints directly to stdout

    print(f"\nDebug bundle collection complete. Output is available in the '{args.output_dir}' directory.")

    if "GITHUB_ACTIONS" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "at") as f:
            print(f'debug_bundle_dir={args.output_dir}', file=f)
    else:
        logging.info("Not running on Github Actions, won't produce GITHUB_OUTPUT")


if __name__ == "__main__":
    main()
