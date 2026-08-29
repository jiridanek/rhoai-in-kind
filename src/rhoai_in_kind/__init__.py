from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
from string.templatelib import Template, Interpolation, convert
from typing import TYPE_CHECKING, ContextManager, Generator, Protocol

if TYPE_CHECKING:
    from types import ModuleType
    from typing import Any, Callable


class Tracer(Protocol):
    """Minimal tracing interface `sh()`/`gha_log_group()` depend on.

    Kept independent of any specific OTel SDK so the `tracing` extra (logfire et al.) can stay
    an optional dependency - see NullTracer/LogfireTracer below.
    """

    def span(self, msg_template: str, /, **attributes: Any) -> ContextManager[None]: ...


class NullTracer:
    """No-op Tracer, active whenever the `tracing` extra isn't installed/configured."""

    def span(self, msg_template: str, /, **attributes: Any) -> ContextManager[None]:
        return contextlib.nullcontext()


class LogfireTracer:
    """Tracer backed by Pydantic Logfire.

    Takes the already-imported `logfire` module rather than importing it itself, so the whole
    "is the `tracing` extra installed" check lives in one place (the caller's try/except
    ImportError) instead of being duplicated here.
    """

    def __init__(self, logfire_module: ModuleType) -> None:
        self._logfire = logfire_module

    def span(self, msg_template: str, /, **attributes: Any) -> ContextManager[None]:
        return self._logfire.span(msg_template, **attributes)


_tracer: Tracer = NullTracer()


def set_tracer(tracer: Tracer) -> None:
    global _tracer
    _tracer = tracer


def get_tracer() -> Tracer:
    return _tracer


def f(template: Template) -> str:
    """Renders a t-string exactly like an f-string."""
    parts = []

    for item in template:
        match item:
            case str(text):
                parts.append(text)

            case Interpolation(value, _, conversion, format_spec):
                assert conversion in ("r", "s", "a") or conversion is None, f"Unsupported conversion: {conversion}"
                transformed = convert(value, conversion)
                formatted = format(transformed, format_spec) if format_spec else str(transformed)
                parts.append(formatted)

    return "".join(parts)


def format_t_string(t: Template) -> tuple[str, dict[str, Any]]:
    template = []
    attributes = {}
    for v in t:
        match v:
            case str(text):
                template.append(text)
            case Interpolation(value, expression, _, _):
                template.append(f"{{{expression}}}")
                attributes[expression] = value
    return "".join(template), attributes


def code(depth: int) -> dict[str, Any]:
    caller_frame = sys._getframe(depth)
    return {
        "code.filepath": caller_frame.f_code.co_filename,
        "code.lineno": caller_frame.f_lineno,
        "code.function": caller_frame.f_code.co_name,
    }


@contextlib.contextmanager
def _span(
    t: Template,
) -> Generator[None, None, None]:
    """Creates a span, attributing it to its caller's call site rather than this function's.

    _span_name is pre-formatted (not the raw "{cmd}" template) so generic OTel viewers
    (e.g., the Aspire dashboard), which display the literal span name, show the real command.

    Private: code(4) assumes exactly one level of wrapping between the real call site and
    this generator (contextmanager frame, this frame, the wrapper's `with` line, the wrapper's
    caller) - true for sh()'s current single call below, but wrong if called any other way.
    """
    # sh() calls this on every invocation (often hundreds per deploy run); skip the frame-walk
    # (code(4)) and template formatting below when there's no real tracer to hand them to.
    if isinstance(_tracer, NullTracer):
        yield
        return
    _span_name = f(t)
    msg_template, attributes = format_t_string(t)
    with _tracer.span(msg_template, _span_name=_span_name, **attributes, **code(4)):
        yield


def sh(
    cmd: str, env: dict[str, str] | None = None,
    input: str | None = None,
    capture_output: bool = False,
    timeout: float|None = None
) -> subprocess.CompletedProcess[str]:
    """Runs a shell command."""
    # No-op without a configured provider (logfire.configure() is only called by entrypoint
    # scripts like deploy.py), so this is safe to leave unconditional here.
    # WARNING: the full cmd string is recorded as a span attribute, so any secret embedded
    # directly in it (not fetched at runtime inside a nested `bash -c`) leaks into the trace
    # backend. This is accepted: this repo only ever handles disposable local
    # kind-cluster/CI credentials, never production secrets.
    with _span(t"sh {cmd}"):
        env = env or {}
        if capture_output:
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
            capture_output=capture_output,
            timeout=timeout,
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
    with _tracer.span(title):
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
