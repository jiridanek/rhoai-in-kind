#!/usr/bin/env python3

from __future__ import annotations

import os
import contextlib
import sys
import subprocess
from typing import Callable


def main():
    tf = TestFrame()

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

    # https://istio.io/latest/docs/setup/platform-setup/kind/
    # https://istio.io/latest/docs/tasks/traffic-management/ingress/gateway-api/#setup
    # https://ryandeangraham.medium.com/istio-gateway-api-nodeport-c598a21c4c95
    with gha_log_group("Install Istio"):
        ISTIO_VERSION = "1.25.1"
        TARGET_ARCH = "x86_64"

        # TLSRoute is considered "experimental"
        # https://github.com/kubernetes-sigs/gateway-api/issues/2643
        sh('kubectl get crd gateways.gateway.networking.k8s.io &> /dev/null || \
          { kubectl kustomize "github.com/kubernetes-sigs/gateway-api/config/crd/experimental?ref=v1.2.1" | kubectl apply -f -; }')

        sh("curl -L https://istio.io/downloadIstio | sh -", env={
            "ISTIO_VERSION": ISTIO_VERSION,
            "TARGET_ARCH": TARGET_ARCH,
        })
        sh(f"istio-{ISTIO_VERSION}/bin/istioctl install --set values.pilot.env.PILOT_ENABLE_ALPHA_GATEWAY_API=true --set profile=minimal -y")

        sh("kubectl apply -f components/06-gateway.yaml")

        tf.defer(None, lambda _: sh(
            "kubectl wait -n istio-system --for=condition=programmed gateways.gateway.networking.k8s.io gateway"))
        # export INGRESS_HOST=$(kubectl get gateways.gateway.networking.k8s.io gateway -n istio-system -ojsonpath='{.status.addresses[0].value}')

    with gha_log_group("Setup Gateway"):
        sh("kubectl apply -f components/06-gateway.yaml")

    with gha_log_group("Install ArgoCD"):
        sh("kubectl create -k components/01-argocd")
        tf.defer(None, lambda _: sh("kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=argocd-server -n argocd --timeout=120s"))

    with gha_log_group("Install Kyverno"):
        sh("kubectl create -k components/02-kyverno")
        tf.defer(None, lambda _: sh("kubectl wait --for=condition=Ready pod -l app.kubernetes.io/part-of=kyverno -n kyverno --timeout=120s"))
        tf.defer(None, lambda _: sh("oc wait --for=condition=Ready clusterpolicy --all"))

    with gha_log_group("Deploy fake CRDs"):
        sh("kubectl apply -k components/crds")

    with gha_log_group("Deploy api-extension"):
        sh("kubectl apply -k components/api-extension")
        tf.defer(None, lambda _: sh("kubectl wait -n api-extension deployment/apiserver --for=condition=Available --timeout=100s"))

        tf.defer(None, lambda _: sh("kubectl logs -n api-extension deployment/apiserver"))

    with gha_log_group("Check that API extension server works"):
        sh("timeout 30s bash -c 'while ! oc new-project dsp-wb-test; do sleep 1; done'")

    with gha_log_group("Run kubectl create namespace redhat-ods-applications"):
        sh("kubectl create namespace redhat-ods-applications")


    with gha_log_group("Run deferred functions"):
        with tf:
            pass


def sh(cmd: str, env: dict[str, str] | None = None):
    """Runs a shell command."""
    env = env or {}
    print(f"$ {cmd}", file=sys.stdout)
    sys.stdout.flush()
    subprocess.check_call(
        "set -Eeuxo pipefail; " + cmd,
        shell=True, executable="/bin/bash",
        env={**os.environ, **env}
    )
    sys.stdout.flush()


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


class TestFrame:
    def __init__(self):
        self.stack = []

    def defer[T](self, obj: T, fn: Callable[[T], None]):
        self.stack.append((obj, fn))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        while self.stack:
            obj, fn = self.stack.pop()
            fn(obj)


if __name__ == "__main__":
    main()
