from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Generator

import logfire

if TYPE_CHECKING:
    from typing import Any, Callable


def sh(
    cmd: str, env: dict[str, str] | None = None,
    input: str | None = None,
    **kwargs
) -> subprocess.CompletedProcess[str]:
    """Runs a shell command."""
    # No-op without a configured provider (logfire.configure() is only called by entrypoint
    # scripts like deploy.py), so this is safe to leave unconditional here.
    # WARNING: the full cmd string is recorded as a span attribute, so any secret embedded
    # directly in it (not fetched at runtime inside a nested `bash -c`) leaks into the trace
    # backend. This is accepted: this repo only ever handles disposable local
    # kind-cluster/CI credentials, never production secrets.
    # _span_name is pre-formatted (not the raw "{cmd}" template) so generic OTel viewers
    # (e.g. the Aspire dashboard), which display the literal span name, show the real command.
    with logfire.span("sh {cmd}", _span_name=f"sh {cmd}", cmd=cmd):
        env = env or {}
        print(f"$ {cmd}", file=sys.stdout)
        sys.stdout.flush()
        completed_process = subprocess.run(
            f"set -Eeuxo pipefail; {cmd}",
            shell=True,
            executable="/bin/bash",
            env={**os.environ, **env},
            input=input,
            check=True,
            text=True,
            **kwargs,
        )
        sys.stdout.flush()
        return completed_process


def create_resource(resource: str):
    sh("kubectl apply -f -", input=resource)


def wait_for_webhook_service_endpoint(namespace: str):
    service_name = "odh-notebook-controller-webhook-service"
    timeout_seconds = 60
    poll_interval_seconds = 1
    start_time = time.time()

    print(f"Waiting for endpoints of service '{service_name}' in namespace '{namespace}' to be ready...")

    while time.time() - start_time < timeout_seconds:
        try:
            # Use oc get endpoints -o json to check for ready addresses
            command = [
                "kubectl", "get", "endpoints", service_name,
                "-n", namespace,
                "-o", "json"
            ]
            result = sh(" ".join(command), capture_output=True, timeout=5)
            endpoints_data = json.loads(result.stdout)

            # Check if 'subsets' exist and contain addresses
            if "subsets" in endpoints_data:
                for subset in endpoints_data["subsets"]:
                    # Check for ready addresses ('addresses') vs not ready ('notReadyAddresses')
                    if "addresses" in subset and subset["addresses"]:
                        print(f"Endpoints for service '{service_name}' are ready.")
                        return

            print(f"Endpoints for '{service_name}' not ready yet, checking again in {poll_interval_seconds}s...")

        except subprocess.CalledProcessError as e:
            # Handle case where endpoints object might not exist yet or other oc errors
            print(f"Error checking endpoints (will retry): {e.stderr}")
        except subprocess.TimeoutExpired:
            print("Timeout during 'oc get endpoints' command (will retry).")
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON output from oc get endpoints (will retry): {e}")
        except Exception as e:
            print(f"An unexpected error occurred (will retry): {e}")

        time.sleep(poll_interval_seconds)

    raise TimeoutError(
        f"Timeout waiting for endpoints of service '{service_name}' in namespace '{namespace}' after {timeout_seconds} seconds.")


# https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/workflow-commands-for-github-actions#grouping-log-lines
@contextlib.contextmanager
def gha_log_group(title: str) -> Generator[None, Any, None]:
    """Prints the starting and ending magic strings for GitHub Actions line group in log."""
    with logfire.span(title):
        print(f"::group::{title}", file=sys.stdout)
        sys.stdout.flush()
        try:
            yield
        finally:
            print("::endgroup::", file=sys.stdout)
            sys.stdout.flush()


class TestFrame:
    def __init__(self):
        self.stack = []

    def defer[T](self, obj: T, fn: Callable[[T], Any]):
        self.stack.append((obj, fn))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        while self.stack:
            obj, fn = self.stack.pop(0)
            fn(obj)
