#!/usr/bin/env python3

import contextlib
import sys
import subprocess


def main():
    with gha_log_group("Install ArgoCD CLI"):
        ARGOCD_VERSION = "v2.14.9"
        sh(f"curl -sSL -o /tmp/argocd-{ARGOCD_VERSION} https://github.com/argoproj/argo-cd/releases/download/{ARGOCD_VERSION}/argocd-linux-amd64")
        sh(f"chmod +x /tmp/argocd-{ARGOCD_VERSION}")
        sh(f"sudo mv /tmp/argocd-{ARGOCD_VERSION} /usr/local/bin/argocd")
        sh("argocd version --client")

    with gha_log_group("Install OC client"):
        sh("curl -L https://mirror.openshift.com/pub/openshift-v4/$(uname -m)/clients/ocp/stable/openshift-client-linux.tar.gz \
                                                               -o /tmp/openshift-client-linux.tar.gz")
        sh("tar -xzvf /tmp/openshift-client-linux.tar.gz oc")
        sh("sudo mv ./oc /usr/local/bin/oc")
        sh("rm -f /tmp/openshift-client-linux.tar.gz")

        sh("oc version")


def sh(cmd: str):
    """Runs a shell command."""
    print(f"$ {cmd}", file=sys.stdout)
    subprocess.check_call(cmd, shell=True)


# https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/workflow-commands-for-github-actions#grouping-log-lines
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


if __name__ == "__main__":
    main()
