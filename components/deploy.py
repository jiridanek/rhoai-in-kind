#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import contextlib
import sys
import subprocess
import textwrap
import time
from typing import Callable, Any

import certs


def main():
    tf = TestFrame()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--workbench-branch",
        default=os.environ.get("WORKBENCH_BRANCH"),
        help="The workbench branch to use. Defaults to the WORKBENCH_BRANCH environment variable.",
        required=not os.environ.get("WORKBENCH_BRANCH"),
    )
    args = parser.parse_args()
    workbench_branch = args.workbench_branch

    # slow to deploy so do it first
    with gha_log_group("Install Kyverno"):
        # https://kubernetes.io/blog/2022/10/20/advanced-server-side-apply/
        sh("timeout 30s bash -c 'while ! kubectl apply --server-side -k components/02-kyverno; do sleep 1; done'")
        tf.defer(None, lambda _: sh(
            "kubectl wait --for=condition=Ready pod -l app.kubernetes.io/part-of=kyverno -n kyverno --timeout=120s"))

    with gha_log_group("Install cert-manager"):
        version = "v1.18.2"
        cert_manager_yaml = f"https://github.com/jetstack/cert-manager/releases/download/{version}/cert-manager.yaml"
        sh(f"kubectl apply -f {cert_manager_yaml}")
        sh("kubectl wait deployment.apps --for condition=Available --selector app.kubernetes.io/instance=cert-manager --all-namespaces --timeout 5m")

    with gha_log_group("Generate certs"):
        certs.ca_issuer()

    if "CI" in os.environ:
        with gha_log_group("Install ArgoCD CLI"):
            ARGOCD_VERSION = "v3.0.6"
            sh(f"curl -sSL -o /tmp/argocd-{ARGOCD_VERSION} https://github.com/argoproj/argo-cd/releases/download/{ARGOCD_VERSION}/argocd-$(go env GOOS)-$(go env GOARCH)")
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
        ISTIO_VERSION = "1.26.2"
        TARGET_ARCH = sh("arch", capture_output=True).stdout.strip()

        # TLSRoute is considered "experimental"
        # https://github.com/kubernetes-sigs/gateway-api/issues/2643
        sh('kubectl get crd gateways.gateway.networking.k8s.io &> /dev/null || \
          { kubectl kustomize "github.com/kubernetes-sigs/gateway-api/config/crd/experimental?ref=v1.3.0" | kubectl apply -f -; }')

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

    with gha_log_group("Configure DNS"):
        sh("kubectl apply -f components/11-coredns.yaml")

    with gha_log_group("Install ArgoCD"):
        sh("kubectl apply -k components/01-argocd")
        tf.defer(None, lambda _: sh(
            "kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=argocd-server -n argocd --timeout=120s"))

    with gha_log_group("Deploy fake CRDs"):
        sh("kubectl apply -k components/crds")

    with gha_log_group("Deploy api-extension"):
        sh("kubectl apply -k components/api-extension")
        tf.defer(None, lambda _: sh(
            "kubectl wait -n api-extension deployment/apiserver --for=condition=Available --timeout=100s"))

        tf.defer(None, lambda _: sh("kubectl logs --tail 10 -n api-extension deployment/apiserver"))

    # with gha_log_group("Check that API extension server works"):
    #     tf.defer(None, lambda _: sh("timeout 30s bash -c 'while ! oc new-project dsp-wb-test; do sleep 1; done'"))

    with gha_log_group("Run kubectl create namespaces redhat-ods-applications"):
        sh("kubectl get namespace redhat-ods-applications || kubectl create namespace redhat-ods-applications")

    with gha_log_group("Setup rhods-notebooks namespace"):
        # c.f. dashboard's validateNotebookNamespaceRoleBinding
        # it will create rolebinding ${notebookNamespace}-image-pullers in dashboardNamespace
        # and it needs a clusterrole system:image-puller to exist, which does not exsist on kind by default
        sh("kubectl get namespace rhods-notebooks || kubectl create namespace rhods-notebooks")
        # dummy verb and resource, just to have something there
        sh("kubectl create clusterrole system:image-puller --verb=list --resource=imagestreams.image.openshift.io --dry-run=client -o yaml | kubectl apply -f -")
        # I have no idea why the next line was needed; it is not mentioned in dashboard sources except in manifests
        # that should've created this already!?!
        sh("kubectl create clusterrole cluster-monitoring-view --verb=list --resource=imagestreams.image.openshift.io --dry-run=client -o yaml | kubectl apply -f -")
        # this is to mitigate fallout from https://github.com/opendatahub-io/odh-dashboard/pull/4049
        # not sure if this is permanent or just a temporary workaround, NOTE: rhods-notebooks serviceaccount!
        # language=Yaml
        dashboardPullerRole = textwrap.dedent("""
        apiVersion: rbac.authorization.k8s.io/v1
        kind: RoleBinding
        metadata:
            name: rhods-notebooks-image-pullers
            namespace: redhat-ods-applications
        roleRef:
            apiGroup: rbac.authorization.k8s.io
            kind: ClusterRole
            name: system:image-puller
        subjects:
            - apiGroup: rbac.authorization.k8s.io
              kind: Group
              name: system:serviceaccounts:rhods-notebooks
        """)
        create_resource(dashboardPullerRole)

    with gha_log_group("Configure Argo applications"):
        sh("kubectl apply -f components/03-kf-pipelines.yaml")
        sh("kubectl apply -f components/04-odh-dashboard.yaml")

    with gha_log_group("Run deferred functions"):
        with tf:
            pass

    with gha_log_group("Install Kyverno policies"):
        sh("timeout 30s bash -c 'while ! kubectl apply -f components/02-kyverno/policy.yaml; do sleep 1; done'")
        sh("timeout 30s bash -c 'while ! kubectl apply -f components/02-kyverno/notebook-routes-policy.yaml; do sleep 1; done'")
        sh("timeout 30s bash -c 'while ! kubectl apply -f components/02-kyverno/pipelines-routes-policy.yaml; do sleep 1; done'")
        sh("timeout 30s bash -c 'while ! kubectl apply -f components/02-kyverno/imagestream-status-policy.yaml; do sleep 1; done'")
        tf.defer(None, lambda _: sh("oc wait --for=condition=Ready clusterpolicy --all"))

    with gha_log_group("Run deferred functions"):
        with tf:
            pass

    with gha_log_group("Install Minio"):
        sh("kubectl get namespace minio || kubectl create namespace minio")
        secret = textwrap.dedent("""
        apiVersion: v1
        kind: Secret
        metadata:
            name: minio-root-user
        type: Opaque
        stringData:
            MINIO_ROOT_USER: AWS_ACCESS_KEY_ID
            MINIO_ROOT_PASSWORD: AWS_SECRET_ACCESS_KEY
        """)
        sh("kubectl apply --namespace=minio -f -", input=secret)
        sh("kubectl apply --namespace=minio -f components/10-minio/deploy.yaml")

        tf.defer(None, lambda _: sh("kubectl wait --for=condition=Available deployment -l app=minio -n minio --timeout=120s"))
        # tf.defer(None, lambda _: sh(
        #     "timeout 120s bash -c 'while ! kubectl get --namespace=minio secret/aws-connection-my-storage; do sleep 1; done'"))
        # tf.defer(None, lambda _: sh(
        #     "timeout 120s bash -c 'while ! kubectl get --namespace=minio secret/aws-connection-pipeline-artifacts; do sleep 1; done'"))
        def create_buckets(_):
            try:
                import boto3
            except ImportError:
                python = sys.executable
                # python = "/opt/homebrew/bin/python3"
                sh(f"{python} -m pip install boto3")
                import boto3

            # MINIO_ROOT_USER=sh("oc get -n minio secret minio-root-user -o template --template '{{.data.MINIO_ROOT_USER}}'", stdout=subprocess.PIPE).stdout.strip()
            MINIO_ROOT_USER="AWS_ACCESS_KEY_ID"
            # MINIO_ROOT_PASSWORD=sh("oc get -n minio secret minio-root-user -o template --template '{{.data.MINIO_ROOT_PASSWORD}}'", stdout=subprocess.PIPE).stdout.strip()
            MINIO_ROOT_PASSWORD="AWS_SECRET_ACCESS_KEY"
            # MINIO_HOST="https://" + sh("oc get -n minio route minio-s3 -o template --template '{{.spec.host}}'", stdout=subprocess.PIPE).stdout.strip()
            MINIO_HOST="https://minio.apps.127.0.0.1.sslip.io"

            s3 = boto3.client("s3",
                              endpoint_url=MINIO_HOST,
                              aws_access_key_id=MINIO_ROOT_USER,
                              aws_secret_access_key=MINIO_ROOT_PASSWORD,
                              verify=False)
            bucket = 'ods-ci-ds-pipelines'
            print('creating ods-ci-ds-pipelines bucket')
            if bucket not in [bu["Name"] for bu in s3.list_buckets()["Buckets"]]:
                s3.create_bucket(Bucket=bucket)
            bucket = 'ods-ci-s3'
            print('creating ods-ci-s3 bucket')
            if bucket not in [bu["Name"] for bu in s3.list_buckets()["Buckets"]]:
                s3.create_bucket(Bucket=bucket)

        tf.defer(None, create_buckets)

    with gha_log_group("Login to ArgoCD"):
        sh("kubectl config set-context --current --namespace=argocd")
        sh("argocd login --core")
        # time="2025-04-10T21:52:51Z" level=error msg="finished unary call with code Unknown" error="error setting cluster info in cache: dial tcp [::1]:42171: connect: connection refused" grpc.code=Unknown grpc.method=Create grpc.service=cluster.ClusterService grpc.start_time="2025-04-10T21:52:51Z" grpc.time_ms=272.867 span.kind=server system=grpc
        sh("timeout 30s bash -c 'while ! argocd cluster add kind-kind --yes; do sleep 1; done'")

    # actually needed, did something that DSP Workbenches dashboard tab won't load without
    with gha_log_group("Install KF Pipelines"):
        # dspa is looking up configmaps in this namespace
        #sh("kubectl create namespace openshift-config-managed --dry-run=client -o yaml | kubectl apply -f -")

        sh("timeout 30s bash -c 'while ! argocd app sync kf-pipelines; do sleep 1; done'")

        # wait for argocd to sync the application
        # wait for deployment as it is more robust
        tf.defer(None, lambda _: sh(
            "oc wait --for=condition=Available deployment -l app.kubernetes.io/name=data-science-pipelines-operator -n redhat-ods-applications --timeout=120s"))

    with gha_log_group("Install KF Notebooks"):
        sh("kubectl apply -k components/09-kf-notebooks")
        tf.defer(None, lambda _: sh(
            "oc wait --for=condition=Available deployment -l app=notebook-controller -n redhat-ods-applications --timeout=120s"))
        tf.defer(None, lambda _: sh(
            "oc wait --for=condition=Available deployment -l app=odh-notebook-controller -n redhat-ods-applications --timeout=120s"))
        tf.defer(None, lambda _: wait_for_webhook_service_endpoint())

    with gha_log_group("Install Workbenches"):
        # error unmarshaling JSON: while decoding JSON: json: unknown field "apiGroup"
        # kustomize_version="5.0.3"
        # with tempfile.TemporaryDirectory() as tmp_dir:
        #     kustomize_tar=f"{tmp_dir}/kustomize-{kustomize_version}.tar.gz"
        #     kustomize_bin=f"{tmp_dir}/kustomize-{kustomize_version}"
        #     print("---------------------------------------------------------------------------------")
        #     print(f"Download kustomize '{kustomize_version}'")
        #     print("---------------------------------------------------------------------------------")
        #     sh(f'wget --output-document="{kustomize_tar}" "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize/v{kustomize_version}/kustomize_v{kustomize_version}_$(go env GOOS)_$(go env GOARCH).tar.gz"')
        #     sh(f'tar -C "{tmp_dir}" -xvf "{kustomize_tar}"')
        #     sh(f'mv "{tmp_dir}/kustomize" "{kustomize_bin}"')
        #
        #     sh(f'"{kustomize_bin}" version')
        #     sh(f"{kustomize_bin} build components/08-workbenches | kubectl apply -f -")
        sh(f"kubectl apply -k 'https://github.com/red-hat-data-services/notebooks//manifests/base/?timeout=90s&ref={workbench_branch}' --namespace redhat-ods-applications")


    with gha_log_group("Install Service CA Operator"):
        sh("kubectl label node --all node-role.kubernetes.io/master=")
        sh("timeout 30s bash -c 'while ! kubectl apply -k components/05-ca-operator; do sleep 1; done'")

    with gha_log_group("Install fake oauth-server"):
        sh("kubectl apply -k components/oauth-server")

    with gha_log_group("Create users"):
        for username in [
            # ods-ci users
            "htpasswd-cluster-admin-user", "admin-user", "ldap-admin1", "ldap-user1", "ldap-user2", "ldap-admin2", "ldap-user9",
            # cypress e2e users
            # foo-user,
            "contributor-username", "adminuser",
        ]:
            sh(f"kubectl create serviceaccount -n oauth-server {username} --dry-run=client -o yaml | kubectl apply -f -")
            # the full SA name is something like `system:serviceaccount:oauth-server:ldap-user2`
            sh(f"kubectl create clusterrolebinding -n oauth-server {username} --clusterrole cluster-admin --user={username} --serviceaccount=oauth-server:{username} --dry-run=client -o yaml | kubectl apply -f -")

    with gha_log_group("Install ODH Dashboard"):
        # was getting a CRD missing error, somehow argo was not waiting to establish OdhDocument?
        sh("timeout 30s bash -c 'while ! argocd app sync odh-dashboard; do sleep 1; done'")
        tf.defer(None, lambda _: sh(
            "kubectl wait --for=condition=Available deployment -l app=rhods-dashboard -n redhat-ods-applications --timeout=120s"))
        # wait for webpage availability
        tf.defer(None, lambda _: sh('''timeout 60s bash -c 'while ! curl -k "https://rhods-dashboard.127.0.0.1.sslip.io/"; do sleep 2; done' '''))

    with gha_log_group("Set fake DSC and DSCI"):
        sh("kubectl apply -f components/07-dsc-dsci.yaml --server-side")
        # need status for dashboard resource otherwise notebook controller will not fill dashboard link for dspa secret
        sh("kubectl apply -f components/07-dsc-dsci.yaml --server-side --subresource=status || true")

    with gha_log_group("Install local-path provisioner"):
        sh("kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.31/deploy/local-path-storage.yaml")
        tf.defer(None, lambda _: sh(
            "kubectl wait deployments --all --namespace=local-path-storage --for=condition=Available --timeout=100s"))
        # https://kubernetes.io/docs/tasks/administer-cluster/change-default-storage-class/
        sh("kubectl get storageclass")
        # kubectl patch storageclass local-path -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
        # dashboard tests expect a storage class that's identified by
        # > oc get storageclass -o jsonpath='{.items[?(@.metadata.annotations.storageclass\.kubernetes\.io/is-default-class=="true")].metadata.name}'
        # and the above delivers, so nothing more to do here
        # most importantly, don't create another `storageclass.kubernetes.io/is-default-class: "true"` thing or the above command returns both, space separated

    with gha_log_group("Run deferred functions"):
        with tf:
            pass


def sh(cmd: str, env: dict[str, str] | None = None, input: str | None = None, **kwargs) -> subprocess.CompletedProcess[str]:
    """Runs a shell command."""
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

def wait_for_webhook_service_endpoint():
    service_name = "odh-notebook-controller-webhook-service"
    namespace = "redhat-ods-applications"
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

    raise TimeoutError(f"Timeout waiting for endpoints of service '{service_name}' in namespace '{namespace}' after {timeout_seconds} seconds.")


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

    def defer[T](self, obj: T, fn: Callable[[T], Any]):
        self.stack.append((obj, fn))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        while self.stack:
            obj, fn = self.stack.pop(0)
            fn(obj)


if __name__ == "__main__":
    main()
