#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import textwrap

import certs

# rhoai_in_kind lives in ../src; put it on the path so this script runs under a
# plain interpreter (CI: `python components/deploy.py`) as well as under an
# editable install (local uv venv).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from rhoai_in_kind import (
    TestFrame,
    create_resource,
    gha_log_group,
    sh,
    wait_for_webhook_service_endpoint,
)

REDHAT_ODS_APPLICATIONS = "redhat-ods-applications"
RHODS_NOTEBOOKS = "rhods-notebooks"

# Ceiling for the ArgoCD retry loops (`timeout <N> bash -c 'while ! argocd ...'`).
# It is a retry budget, not a fixed wait: the loop exits as soon as the command succeeds.
ARGOCD_TIMEOUT = "60s"


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
          { kubectl kustomize "github.com/kubernetes-sigs/gateway-api/config/crd/experimental?ref=v1.3.0&depth=1" | kubectl apply -f -; }')

        if not pathlib.Path(f"istio-{ISTIO_VERSION}/bin/istioctl").exists():
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

    with gha_log_group(f"Run kubectl create namespaces {REDHAT_ODS_APPLICATIONS}"):
        sh(f"kubectl get namespace {REDHAT_ODS_APPLICATIONS} || kubectl create namespace {REDHAT_ODS_APPLICATIONS}")

    with gha_log_group(f"Setup {RHODS_NOTEBOOKS} namespace"):
        # c.f. dashboard's validateNotebookNamespaceRoleBinding
        # it will create rolebinding ${notebookNamespace}-image-pullers in dashboardNamespace
        # and it needs a clusterrole system:image-puller to exist, which does not exsist on kind by default
        sh(f"kubectl get namespace {RHODS_NOTEBOOKS} || kubectl create namespace {RHODS_NOTEBOOKS}")
        # dummy verb and resource, just to have something there
        sh("kubectl create clusterrole system:image-puller --verb=list --resource=imagestreams.image.openshift.io --dry-run=client -o yaml | kubectl apply -f -")
        # I have no idea why the next line was needed; it is not mentioned in dashboard sources except in manifests
        # that should've created this already!?!
        sh("kubectl create clusterrole cluster-monitoring-view --verb=list --resource=imagestreams.image.openshift.io --dry-run=client -o yaml | kubectl apply -f -")
        # this is to mitigate fallout from https://github.com/opendatahub-io/odh-dashboard/pull/4049
        # not sure if this is permanent or just a temporary workaround, NOTE: rhods-notebooks serviceaccount!
        # language=Yaml
        dashboardPullerRole = textwrap.dedent(f"""
        apiVersion: rbac.authorization.k8s.io/v1
        kind: RoleBinding
        metadata:
            name: {RHODS_NOTEBOOKS}-image-pullers
            namespace: {REDHAT_ODS_APPLICATIONS}
        roleRef:
            apiGroup: rbac.authorization.k8s.io
            kind: ClusterRole
            name: system:image-puller
        subjects:
            - apiGroup: rbac.authorization.k8s.io
              kind: Group
              name: system:serviceaccounts:{RHODS_NOTEBOOKS}
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
            MINIO_ROOT_USER = "AWS_ACCESS_KEY_ID"
            # MINIO_ROOT_PASSWORD=sh("oc get -n minio secret minio-root-user -o template --template '{{.data.MINIO_ROOT_PASSWORD}}'", stdout=subprocess.PIPE).stdout.strip()
            MINIO_ROOT_PASSWORD = "AWS_SECRET_ACCESS_KEY"
            # MINIO_HOST="https://" + sh("oc get -n minio route minio-s3 -o template --template '{{.spec.host}}'", stdout=subprocess.PIPE).stdout.strip()
            MINIO_HOST = "https://minio.apps.127.0.0.1.sslip.io"

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
        # ArgoCD pods may still be starting (slow image pulls); wait until they are Available so
        # login / cluster-add do not race a not-yet-ready server.
        sh("kubectl wait --for=condition=Available deployment --all -n argocd --timeout=180s")
        # Log in to argocd-server through the Istio gateway (components/01-argocd/httproute.yaml)
        # rather than core mode: core mode's ephemeral repo-server port-forward is fragile under
        # load (mux: server closed). https://github.com/jiridanek/rhoai-in-kind/issues/40
        # `set +x` in the inner shell keeps the admin password out of the `set -x` trace.
        sh(
            f"""timeout {ARGOCD_TIMEOUT} bash -c '
                set +x
                pw=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{{.data.password}}" | base64 --decode)
                while ! argocd login argocd.apps.127.0.0.1.sslip.io --username admin --password "$pw" --grpc-web --insecure; do sleep 2; done
            '"""
        )
        # No `argocd cluster add` needed: every Application targets the in-cluster endpoint
        # (https://kubernetes.default.svc). Registering the external kind-kind context would also
        # fail in server mode, because argocd-server (in-pod) cannot reach its host-only
        # 127.0.0.1:6443 to validate the cluster.

    # actually needed, did something that DSP Workbenches dashboard tab won't load without
    with gha_log_group("Install KF Pipelines"):
        # dspa is looking up configmaps in this namespace
        # sh("kubectl create namespace openshift-config-managed --dry-run=client -o yaml | kubectl apply -f -")

        sh(f"timeout {ARGOCD_TIMEOUT} bash -c 'while ! argocd app sync kf-pipelines; do sleep 1; done'")

        # wait for argocd to sync the application
        # wait for deployment as it is more robust
        tf.defer(None, lambda _: sh(
            f"oc wait --for=condition=Available deployment -l app.kubernetes.io/name=data-science-pipelines-operator -n {REDHAT_ODS_APPLICATIONS} --timeout=120s"))

        # Only reachable once the sync above has installed DSPO's CRDs. Applying this any
        # earlier (e.g. alongside "Install Kyverno policies") races Kyverno's GVK/GVR
        # resolution for the DataSciencePipelinesApplication kind and was observed to block
        # the readiness wait for every ClusterPolicy, not just this one (PR #70).
        sh("timeout 30s bash -c 'while ! kubectl apply -f components/02-kyverno/dspa-pipelinestore-policy.yaml; do sleep 1; done'")
        tf.defer(None, lambda _: sh("oc wait --for=condition=Ready clusterpolicy/force-dspa-pipelinestore-database"))

    with gha_log_group("Install KF Notebooks"):
        sh("kubectl apply -k components/09-kf-notebooks")
        tf.defer(None, lambda _: sh(
            f"oc wait --for=condition=Available deployment -l app=notebook-controller -n {REDHAT_ODS_APPLICATIONS} --timeout=120s"))
        tf.defer(None, lambda _: sh(
            f"oc wait --for=condition=Available deployment -l app=odh-notebook-controller -n {REDHAT_ODS_APPLICATIONS} --timeout=120s"))
        tf.defer(None, lambda _: wait_for_webhook_service_endpoint(namespace=REDHAT_ODS_APPLICATIONS))

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

        # we don't have permissions to pull from quay.io/rhoai
        # workbench_repo = "https://github.com/red-hat-data-services/notebooks"
        workbench_repo = "https://github.com/opendatahub-io/notebooks"
        sh(f"kubectl apply -k '{workbench_repo}//manifests/base/?timeout=90s&ref={workbench_branch}&depth=1&submodules=false' --namespace {REDHAT_ODS_APPLICATIONS}",
           env={"GIT_LFS_SKIP_SMUDGE": "1"})

    with gha_log_group("Alias minimal workbench imagestream to the downstream name"):
        # opendatahub-tests' workbench tests request the downstream image name
        # `s2i-minimal-notebook` (opendatahub-tests tests/workbenches/conftest.py:44; the
        # distribution is derived from our DSC release.name "OpenShift AI Self-Managed" =>
        # downstream). We deploy the upstream `jupyter-minimal-notebook` imagestream, so create a
        # downstream-named alias of it. The odh-notebook-controller mutating webhook
        # (SetContainerImageFromRegistry) resolves the workbench image from this imagestream's
        # status.tags[].dockerImageReference. This is the only imagestream the tests reference.
        # https://github.com/jiridanek/rhoai-in-kind/issues/48
        import json

        # status.tags[].items[].dockerImageReference is filled in by the best-effort
        # mutate-imagestream-add-simplified-status Kyverno policy, so don't assume it is present
        # the instant the workbench manifests apply — wait until the source has a resolved
        # reference, otherwise the alias could be created without a resolvable workbench image.
        sh(
            f"""timeout 120s bash -c 'while [ -z "$(kubectl -n {REDHAT_ODS_APPLICATIONS} get imagestream jupyter-minimal-notebook -o jsonpath="{{.status.tags[*].items[*].dockerImageReference}}" 2>/dev/null)" ]; do sleep 2; done'"""
        )
        src = json.loads(sh(
            f"kubectl -n {REDHAT_ODS_APPLICATIONS} get imagestream jupyter-minimal-notebook -o json",
            capture_output=True).stdout)
        labels = {
            k: v for k, v in (src["metadata"].get("labels") or {}).items()
            # don't advertise the alias as a dashboard workbench image, or it shows up as a
            # duplicate entry in the spawner next to jupyter-minimal-notebook
            if k != "opendatahub.io/notebook-image"
        }
        src["metadata"] = {
            "name": "s2i-minimal-notebook",
            "namespace": REDHAT_ODS_APPLICATIONS,
            "labels": labels,
            # not operator-managed: this alias is maintained here, not by the ODH operator
            "annotations": {"opendatahub.io/managed": "false"},
        }
        # carry over the (now-resolved) status.tags so the alias resolves regardless of whether
        # the Kyverno mutation fires again on this create.
        sh("kubectl apply -f -", input=json.dumps(src))

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
        sh(f"timeout {ARGOCD_TIMEOUT} bash -c 'while ! argocd app sync odh-dashboard; do sleep 1; done'")
        tf.defer(None, lambda _: sh(
            f"kubectl wait --for=condition=Available deployment -l app=rhods-dashboard -n {REDHAT_ODS_APPLICATIONS} --timeout=120s"))
        # wait for webpage availability
        tf.defer(None, lambda _: sh('''timeout 60s bash -c 'while ! curl -k "https://rhods-dashboard.127.0.0.1.sslip.io/"; do sleep 2; done' '''))

    with gha_log_group("Set fake DSC and DSCI"):
        sh("kubectl apply -f components/07-dsc-dsci.yaml --server-side")
        # need status for dashboard resource otherwise notebook controller will not fill dashboard link for dspa secret
        sh("kubectl apply -f components/07-dsc-dsci.yaml --server-side --subresource=status || true")

    with gha_log_group("Check storage class"):
        # kind already creates its own default StorageClass at cluster creation time (named
        # "standard", provisioner rancher.io/local-path, annotated is-default-class: "true") -
        # this used to also `kubectl apply` rancher/local-path-provisioner's own upstream
        # manifest on top of that, which just installed a second, non-default StorageClass
        # named "local-path" that nothing referenced (confirmed via a real CI run's `kubectl
        # get storageclass` output: only "standard" was ever marked (default), the manually
        # installed "local-path" one sat unused). Dashboard tests look up whichever class
        # carries the is-default-class annotation dynamically, not by a hardcoded name - see
        # > oc get storageclass -o jsonpath='{.items[?(@.metadata.annotations.storageclass\.kubernetes\.io/is-default-class=="true")].metadata.name}'
        # - so kind's own bundled StorageClass already satisfies that without any extra step.
        sh("kubectl get storageclass")

    with gha_log_group("Run deferred functions"):
        with tf:
            pass


if __name__ == "__main__":
    main()
