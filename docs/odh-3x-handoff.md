# RHOAI 3.x in-kind handoff

Date: 2026-09-13
Worktree: /tmp/rhoai-odh3x
Branch: odh-3x-probe
Do not modify the main Issue-10 checkout or kubezoo-e2e-test.

## Objective

Make the RHOAI/ODH 3.3 in-kind base run the real opendatahub-tests 3.3 workbench/notebook suite, using the behavior that passed in the 2.x GHA lane. User selected the real 3.x suite, not a synthetic compatibility test.

## Session 2 results (2026-09-13)

Bottom line: the notebook auth-sidecar blocker is fixed, and the meaningful readiness test test_auth_container_resource_customization now passes end-to-end (as the unprivileged ldap-user1, through the fake OAuth at 127.0.0.1:8443). Two defects had to be fixed; the second was the one predicted by the earlier "memory limit 256Mi, memory request 0" observation.

### The exact 3.3 sidecar image (authoritative, from the controller's own base)

The correct reference is NOT the quay.io/rhoai/odh-kube-rbac-proxy-rhel9 candidate from the Slack research. The v1.10.0-15 notebook controller's own base pins it, and that is the authoritative, version-matched answer (components/odh-notebook-controller/config/base/params.env at v1.10.0-15):

    kube-rbac-proxy=quay.io/opendatahub/odh-kube-auth-proxy@sha256:dcb09fbabd8811f0956ef612a0c9ddd5236804b9bd6548a0647d2b531c9d01b3

That is the ODH-customized kube-auth-proxy wrapper (RHOAIENG-35698). It is digest-pinned, pullable (verified with crane digest / crane manifest), and matches the controller's --kube-rbac-proxy-image arg surface exactly. It is the same value the base's own kustomize replacements already ship, so the patch and the base now agree.

### Fix 1 - sidecar image (commit 9a63cad)

components/09-kf-notebooks/kustomization.yaml: replace the --kube-rbac-proxy-image (args.1) substitution from quay.io/jdanek/origin-oauth-proxy:latest to the digest above. 2.x (branch Issue-10, v1.10.0-5) keeps the origin-oauth-proxy fake; this override lives only on odh-3x-probe.

Verified on the probe cluster: the injected kube-rbac-proxy sidecar now runs (no crash loop), the notebook reaches 2/2 Ready, and the real controller generates everything the sidecar needs: <nb>-kube-rbac-proxy-tls (kubernetes.io/tls), <nb>-kube-rbac-proxy-config (the per-notebook SAR policy: verb get / resource notebooks / name <nb>), the ServiceAccount, the HTTPRoute nb-<ns>-<nb>, the <nb>/<nb>-kube-rbac-proxy Services, and the notebook-httproute-access ReferenceGrant. The SA can create SubjectAccessReviews (kubectl auth can-i create subjectaccessreviews --as=system:serviceaccount:<ns>:<nb> = yes).

### Fix 2 - the "second compatibility issue": the CPU-budget Kyverno policy (commit b61fc6b)

With the image fixed, the pod reached Ready but test_auth_container_resource_customization still failed: the sidecar showed cpu unset and memory request "0". Root cause: the in-kind remove-cpu-memory-requests MutatingPolicy (components/02-kyverno/policy.yaml) strips cpu requests AND limits from every container and forces requests/memory to "0" (a small-kind-node CPU-budget workaround). It ran after the controller's webhook set the sidecar resources from the annotations.

Fix: exclude the kube-rbac-proxy container from that policy's CEL mutation (g.list.filter(c, !has(c.name) || c.name != "kube-rbac-proxy") before .map; g.list.indexOf(c) still resolves the original index, so it is index-safe). System pods (dashboard, main notebook container) are still stripped. Verified: a notebook with the four auth-sidecar annotations now spawns a sidecar with exactly requests{cpu:200m,memory:128Mi} limits{cpu:500m,memory:256Mi}, pod 2/2 Ready; a plain pod is still cpu-stripped.

### Test results (KUBECONFIG isolated to the htpasswd 8443 context)

Ran with an isolated KUBECONFIG copy (never touched ~/.kube/config) pointed at default/127-0-0-1:8443/system:serviceaccount:oauth-server:htpasswd-cluster-admin-user, plus OC_BINARY_PATH=/usr/local/bin/oc and UV_CACHE_DIR (the sandbox denies ~/.cache/uv).

- tests/workbenches/notebooks_server/controller/test_spawning.py: 2/2 PASS (test_create_simple_notebook is still a no-op body, but its fixtures now run against a working controller; test_auth_container_resource_customization PASSES all four resource assertions).
- tests/workbenches/notebooks_server/operator/test_imagestream_health.py: 3 FAIL - infrastructure gaps, NOT sidecar issues (see Remaining 3.x gaps).

### Commits added this session (odh-3x-probe)

- 1216191 probe: shim the 3.x test-suite fixtures (Authentication CRD, operator CSV) and 3.3 workbench tag
- b61fc6b probe: stop the CPU-budget Kyverno policy from stripping the notebook auth sidecar
- 9a63cad probe: point the 3.x notebook auth sidecar at the real ODH kube-auth-proxy digest

(The 3.3 semver tag, fake Authentication CRD, and rhods-operator.3.3.1 CSV from the prior session are now committed in 1216191.)

### Remaining 3.x gaps (not sidecar blockers)

- Full workbench ImageStream set: test_workbench_imagestreams_health expects 11 ImageStreams labeled opendatahub.io/notebook-image=true,platform.opendatahub.io/part-of=workbenches and 7 labeled opendatahub.io/runtime-image=true,...; the in-kind base ships only the 2 minimal streams, unlabeled (found 0). A real 3.x dashboard operator creates these; the probe does not.
- OperatorHub CR shim: test_workbench_imagestreams_older_tags_health calls is_disconnected_cluster, which needs an OperatorHub (config.openshift.io/v1, name cluster). Not shimmed (add alongside the Authentication CRD in components/crds).
- BYOIDC (deferred, per the earlier plan): model token audience/issuer + SAR behavior per RHOAIENG-54751 before adding BYOIDC tests. The fake Authentication/cluster shim is the starting point.

### GHA 3.3 wiring (separate follow-up, not done)

rhoai-in-kind-with-odh-tests-shiftleft.yaml still checks out the 2.x-era opendatahub-tests commit (94670b3) and runs the 2.x tests/workbenches path. A 3.3 lane needs (on odh-3x-probe, kept separate from the main 2.x workflow):
1. test_ref -> a 3.3 opendatahub-tests ref (probe checkout is commit 52e72f5, /tmp/odh-tests-3x).
2. The 3.x suite path tests/workbenches/notebooks_server/... (2.x is tests/workbenches/notebook-controller/...).
3. workbench_branch -> the 3.x workbench ref (currently matrix v1.36.0, a 2.x ref).
4. The opendatahub-tests sub-project UV_PYTHON (3.3 checkout uses 3.13; the 2.x lane's 3.14 side effect does not apply).
5. Deselect/keep set: 3.x has test_auth_container_resource_customization (now passes) - do NOT deselect it the way 2.x deselects test_oauth_container_resource_customization; keep it, and deselect tests/workbenches/notebooks_server/operator/test_imagestream_health.py until the ImageStream substrate + OperatorHub shim land.

## Verified deployment

- Dashboard v3.3.1-odh; MaaS UI omitted.
- DSPO v2.18.0.
- Kubeflow/ODH notebook controllers v1.10.0-15.
- Fake control-plane CRDs under components/crds.
- Fake Authentication CRD plus Authentication/cluster instance.
- Minimal rhods-operator.3.3.1 CSV for product-version resolution.
- Kyverno injection of notebooks.opendatahub.io/inject-auth=true.
- Fake OAuth/API endpoint via nginx at 127.0.0.1:8443.

Before every pytest run, restore the nginx admin context:

    kubectl config use-context "default/127-0-0-1:8443/system:serviceaccount:oauth-server:htpasswd-cluster-admin-user"

Do not run pytest with kind-kind; kubeconfig is shared and context changes cause misleading auth failures.

## Test results and false green

The command used was:

    cd /tmp/odh-tests-3x
    UV_PYTHON=3.13 OC_BINARY_PATH=/usr/local/bin/oc uv run pytest tests/workbenches/notebooks_server/controller/test_spawning.py -v

Important: test_create_simple_notebook is a false green in the current 3.3 branch. Its function signature does not include the notebook_pod fixture; the body is empty. The docstring claims readiness validation, but pytest never instantiates that fixture. It passes without verifying a Ready pod.

test_auth_container_resource_customization is the real readiness check and currently fails after about six minutes. The notebook container becomes Ready, but kube-rbac-proxy enters CrashLoopBackOff.

Observed sidecar:

- Image: quay.io/jdanek/origin-oauth-proxy:latest.
- Args include kube-rbac-proxy arguments: --secure-listen-address, --proxy-endpoints-port, --config-file, --tls-cert-file, etc.
- Logs are the origin-oauth-proxy help text; the binary rejects kube-rbac-proxy arguments.
- A manually-created Notebook with no auth resource annotations reproduced the same crash.

The auth test additionally requests:

- notebooks.opendatahub.io/auth-sidecar-cpu-request: 200m
- notebooks.opendatahub.io/auth-sidecar-memory-request: 128Mi
- notebooks.opendatahub.io/auth-sidecar-cpu-limit: 500m
- notebooks.opendatahub.io/auth-sidecar-memory-limit: 256Mi

The generated pod showed memory limit 256Mi and memory request 0; CPU and requested memory were not applied. This may be a second compatibility issue, but the wrong proxy image is the first blocker.

## Root cause and likely fix

RHOAI 2.x used OpenShift OAuth proxy semantics. The in-kind base replaces OAuth-proxy image references with quay.io/jdanek/origin-oauth-proxy:latest. RHOAI 3.x notebook auth uses kube-rbac-proxy semantics. The same replacement is invalid: an OAuth-proxy binary is receiving kube-rbac-proxy command-line arguments.

Use a real kube-rbac-proxy image for the 3.x notebook controller, while retaining origin-oauth-proxy for genuine 2.x/OpenShift-OAuth consumers. The shared patch is components/09-kf-notebooks/kustomization.yaml:45, where the notebook controller manager image is replaced with origin-oauth-proxy.

Candidate images resolved locally with crane digest:

- quay.io/brancz/kube-rbac-proxy:v0.19.1 -> sha256:9f21034731c7c3228611b9d40807f3230ce8ed2b286b913bf2d1e760d8d866fc
- quay.io/brancz/kube-rbac-proxy:v0.18.2 -> sha256:7de54b6dedc8006ffd447267b826eb417a648c00f2b735b6d313395411803719
- registry.k8s.io/kubebuilder/kube-rbac-proxy:v0.15.0 -> sha256:d8cc6ffb98190e8dd403bfe67ddcb454e6127d32b87acc237b3e5240f70a20fb

Do not assume the newest candidate is correct. Confirm the exact 3.3 reference from the real cluster/release manifests, then pin by digest. Prefer a 3.x-only overlay or deploy-time patch so the 2.x lane is unchanged.

## ImageStream fix already implemented

The 3.x default stable-track resolver requires a semver ImageStream tag and digest-pinned dockerImageReference. The upstream stream only had legacy 2025.1/2025.2 tags.

components/deploy.py now exposes a 3.3 tag on both jupyter-minimal-notebook and s2i-minimal-notebook, resolving the newest legacy image with crane when available and falling back to an existing digest-pinned tag. On the probe cluster it resolved to:

    quay.io/opendatahub/odh-workbench-jupyter-minimal-cpu-py312-ubi9@sha256:ac660bfd55f79086fb12f8c83f9d586baf7b03208fe9cb61154d65553400e5b9

This part is verified: the resolver selects 3.3 without --tc workbench_image_tag.

## Auth / BYOIDC (user said “bring-your-own-odbc”; likely BYOIDC)

Treat BYOIDC separately from Notebook auth sidecars:

1. Confirm the exact 3.x Authentication/OAuth API surface expected by odh-tests and dashboard tests.
2. Determine whether BYOIDC tests expect OAuthClient, OAuthServer, Routes, user APIs, or only Authentication config.
3. Keep Authentication/cluster as a compatibility shim; add behavior only when a test demonstrates the need.
4. Verify bearer-token and browser/cookie identity flows through nginx.
5. Determine whether 3.x still uses the fake OAuth server or requires a true OIDC provider.
6. Do not conflate BYOIDC with kube-rbac-proxy. The latter uses Kubernetes service-account/RBAC semantics; it is not an OAuth provider.

Likely additional 3.x auth gaps: ServiceAccount creation/injection, kube-rbac-proxy-tls Secret generation, proxy ConfigMaps, RBAC bindings, user/group APIs, and route/ingress TLS.

## Current commits and uncommitted changes

Recent commits:

- c0248d9: inject Notebook auth annotation.
- a6145aa: record full 3.x stack and refs.
- fe6caab: DSPO 3.x ref.
- 39c6ab3: Kubeflow notebook controller 3.x ref.
- 8c8a7de: omit MaaS UI.

Intended uncommitted changes:

- components/crds/auth.yaml
- components/crds/rhods-operator-csv.yaml
- components/crds/kustomization.yaml
- components/deploy.py

Generated/untracked artifacts should not be committed: certificates, istio-1.26.2/, nginx certs, and Python __pycache__ directories.

## Recommended next sequence

1. Confirm the exact 3.3 kube-rbac-proxy image from the reference cluster or release manifests.
2. Add a 3.x-only image patch/overlay; do not replace the 2.x OAuth fake globally.
3. Apply that patch to the probe cluster.
4. Create Notebooks with and without auth annotations; verify sidecar image, args, resources, readiness, TLS Secret, and ConfigMap.
5. Run the real auth customization test and assert all four requested resource values.
6. Run the complete relevant 3.3 workbench suite; do not rely on the empty test_create_simple_notebook.
7. Wire the 3.3 test checkout/ref into GHA separately. Current rhoai-in-kind-with-odh-tests-shiftleft.yaml still checks out a 2.x-era commit and runs the old suite.
8. Commit in small increments, then document BYOIDC/BYO identity gaps and coverage.

## Useful commands

    kubectl config use-context "default/127-0-0-1:8443/system:serviceaccount:oauth-server:htpasswd-cluster-admin-user"
    kubectl -n <ns> get pod <pod> -o json
    kubectl -n <ns> logs <pod> -c kube-rbac-proxy --tail=100
    kubectl -n redhat-ods-applications get imagestream s2i-minimal-notebook -o json

## Safety

Do not touch kubezoo-e2e-test. Do not modify the main Issue-10 checkout. Probe work belongs on odh-3x-probe in /tmp/rhoai-odh3x.

## Slack and Jira research (2026-09-13)

### RHOAI-specific proxy image

Slack search found repeated Konflux/RHOAI operator updates for the component image:

- Image repository: https://quay.io/rhoai/odh-kube-rbac-proxy-rhel9
- Source repository: https://github.com/red-hat-data-services/kube-rbac-proxy
- The image is updated by the RHOAI operator/Konflux pipeline, for example operator PRs titled "update odh-kube-rbac-proxy-v3-5".

This is better evidence than the generic quay.io/brancz or registry.k8s.io candidates. The next implementation should identify the exact 3.3 tag/digest used by the 3.3 notebook controller, preferably from the reference cluster's Notebook controller deployment or the rhoai-3.3 operator manifests, then use that RHOAI image in the 3.x-only patch.

Slack search result example:
https://red-hat-internal.slack.com/archives/C0AHR9FTE5P/p1789102734924869

### BYOIDC findings

Jira RHOAIENG-54751: "RHOAI 3.3 - BYOIDC integration with Entra ID does not work due to access token mismatch".

Issue URL:
https://redhat.atlassian.net/browse/RHOAIENG-54751

Important technical finding from the issue: kube-auth-proxy forwarded the Entra access_token downstream, but the token was scoped to Microsoft Graph by default and failed Kubernetes SubjectAccessReview. The dashboard showed Unauthorized and kube-rbac-proxy logs contained SAR-related errors. The issue was marked Blocker and Closed.

Implication for this project: BYOIDC validation must include token audience/scope and Kubernetes SAR behavior. A successful OAuth redirect or dashboard login is insufficient. The fake identity path needs tests for:

- token audience and issuer;
- authenticated username/groups claims;
- SAR allow/deny decisions;
- forwarding behavior from kube-auth-proxy to downstream services;
- bearer-token versus browser/cookie flows.

Jira RHOAIENG-56512: "Reviewing amended the BYOIDC testing strategy for RHOAI 3.4".

Issue URL:
https://redhat.atlassian.net/browse/RHOAIENG-56512

This indicates that BYOIDC test strategy is actively evolving and should not be inferred solely from the 2.x fake OAuth implementation.

### Search caveat

Atlassian semantic search returned broad results; direct issue fetches above were used for the concrete findings. Confluence content retrieval requires a content URL in this integration, so the Notebooks 2.0 FAQ was discovered but not fetched. The local handoff remains the source of probe-specific state.

## Revised next direction

1. Inspect the real RHOAI 3.3 cluster's Notebook controller Deployment and record the exact kube-rbac-proxy image and digest.
2. Search the rhoai-3.3 operator manifests/release metadata for odh-kube-rbac-proxy-rhel9 tag mapping.
3. Add a 3.x-only patch replacing the current origin-oauth-proxy substitution; keep 2.x OAuth proxy behavior unchanged.
4. Re-run the auth customization test and inspect all sidecar resources and readiness.
5. Add BYOIDC research/tests only after the kube-rbac-proxy baseline works; explicitly model token audience and SAR behavior based on RHOAIENG-54751.
