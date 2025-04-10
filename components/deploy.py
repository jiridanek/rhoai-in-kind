#!/usr/bin/env python3

from __future__ import annotations

import os
import contextlib
import sys
import subprocess
import textwrap
from typing import Callable


def main():
    tf = TestFrame()

    # slow to deploy so do it first
    with gha_log_group("Install Kyverno"):
        sh("kubectl create -k components/02-kyverno")
        tf.defer(None, lambda _: sh(
            "kubectl wait --for=condition=Ready pod -l app.kubernetes.io/part-of=kyverno -n kyverno --timeout=120s"))

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
        tf.defer(None, lambda _: sh(
            "kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=argocd-server -n argocd --timeout=120s"))

    with gha_log_group("Deploy fake CRDs"):
        sh("kubectl apply -k components/crds")

    with gha_log_group("Deploy api-extension"):
        sh("kubectl apply -k components/api-extension")
        tf.defer(None, lambda _: sh(
            "kubectl wait -n api-extension deployment/apiserver --for=condition=Available --timeout=100s"))

        tf.defer(None, lambda _: sh("kubectl logs --tail 10 -n api-extension deployment/apiserver"))

    with gha_log_group("Check that API extension server works"):
        tf.defer(None, lambda _: sh("timeout 30s bash -c 'while ! oc new-project dsp-wb-test; do sleep 1; done'"))

    with gha_log_group("Run kubectl create namespace redhat-ods-applications"):
        sh("kubectl create namespace redhat-ods-applications")

    with gha_log_group("Configure Argo applications"):
        sh("kubectl apply -f components/03-kf-pipelines.yaml")
        sh("kubectl apply -f components/04-odh-dashboard.yaml")

    with gha_log_group("Run deferred functions"):
        with tf:
            pass

    with gha_log_group("Install Kyverno policies"):
        sh("timeout 30s bash -c 'while ! kubectl apply -f components/02-kyverno/policy.yaml; do sleep 1; done'")
        tf.defer(None, lambda _: sh("oc wait --for=condition=Ready clusterpolicy --all"))

    with gha_log_group("Run deferred functions"):
        with tf:
            pass

    with gha_log_group("Login to ArgoCD"):
        sh("kubectl config set-context --current --namespace=argocd")
        sh("argocd login --core")
        # time="2025-04-10T21:52:51Z" level=error msg="finished unary call with code Unknown" error="error setting cluster info in cache: dial tcp [::1]:42171: connect: connection refused" grpc.code=Unknown grpc.method=Create grpc.service=cluster.ClusterService grpc.start_time="2025-04-10T21:52:51Z" grpc.time_ms=272.867 span.kind=server system=grpc
        sh("argocd cluster add kind-kind --yes")

    # actually needed, did something that DSP Workbenches dashboard tab won't load without
    with gha_log_group("Install KF Pipelines"):
        sh("timeout 30s bash -c 'while ! argocd app sync kf-pipelines; do sleep 1; done'")

        # wait for argocd to sync the application
        tf.defer(None, lambda _: sh(
            "kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=data-science-pipelines-operator -n redhat-ods-applications --timeout=120s"))

    with gha_log_group("Install KF Notebooks"):
        sh("kubectl apply -k components/09-kf-notebooks")

    with gha_log_group("Install Workbenches"):
        sh("kubectl apply -k components/08-workbenches")

    with gha_log_group("Install Service CA Operator"):
        sh("kubectl label node --all node-role.kubernetes.io/master=")
        sh("timeout 30s bash -c 'while ! kubectl apply -k components/05-ca-operator; do sleep 1; done'")

    with gha_log_group("Install fake oauth-server"):
        sh("kubectl apply -k components/oauth-server")

    with gha_log_group("Create admin-user"):
        sh("kubectl create serviceaccount -n oauth-server admin-user")
        sh("kubectl create clusterrolebinding -n oauth-server admin-user --clusterrole cluster-admin --serviceaccount=oauth-server:admin-user")

    with gha_log_group("Install ODH Dashboard"):
        # was getting a CRD missing error, somehow argo was not waiting to establish OdhDocument?
        sh("timeout 30s bash -c 'while ! argocd app sync odh-dashboard; do sleep 1; done'")

    with gha_log_group("Set fake DSC and DSCI"):
        sh("kubectl apply -f components/07-dsc-dsci.yaml")

    with gha_log_group("Install local-path provisioner"):
        sh("kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.31/deploy/local-path-storage.yaml")
        tf.defer(None, lambda _: sh(
            "kubectl wait deployments --all --namespace=local-path-storage --for=condition=Available --timeout=100s"))
        # https://kubernetes.io/docs/tasks/administer-cluster/change-default-storage-class/
        sh("kubectl get storageclass")
        # kubectl patch storageclass local-path -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
        # dashboard tests expect a storage class standard-csi
        sh("kubectl apply -f -", input=textwrap.dedent("""
          ---
          apiVersion: storage.k8s.io/v1
          kind: StorageClass
          metadata:
            annotations:
              storageclass.kubernetes.io/is-default-class: "true"
            name: standard-csi
          provisioner: rancher.io/local-path
          reclaimPolicy: Delete
          volumeBindingMode: WaitForFirstConsumer
          """))

    with gha_log_group("Run deferred functions"):
        with tf:
            pass


def sh(cmd: str, env: dict[str, str] | None = None, input: str | None = None):
    """Runs a shell command."""
    env = env or {}
    print(f"$ {cmd}", file=sys.stdout)
    sys.stdout.flush()
    subprocess.run(
        "set -Eeuxo pipefail; " + cmd,
        shell=True, executable="/bin/bash",
        env={**os.environ, **env},
        input=input,
        check=True, text=True,
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
            obj, fn = self.stack.pop(0)
            fn(obj)


if __name__ == "__main__":
    main()
