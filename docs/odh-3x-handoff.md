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

## Elyra / Cypress browser-test session (3.x in-kind)

Objective: run the shorter Elyra Sanity robot test (ods-ci) plus a couple of cypress workbenches specs against the 3.x in-kind probe. Time-boxed scope: fix gateway routing + install chromedriver.

### Infrastructure fixed (driver/browser/cluster now work end-to-end for launch)

1. **Gateway routing (dashboard external URL was 000/unreachable).** Root cause was NOT istio SNI/mTLS but a **NetworkPolicy**: `rhods-dashboard-allow-ports` (redhat-ods-applications) only allows ingress from pods in a namespace labeled `network.openshift.io/policy-group=ingress` (or same-namespace pods). `istio-system` (the meshless `gateway`) lacked the label, so gateway→dashboard:8443 was silently dropped. Fix (currently live cluster state only — must be persisted into deploy.py):
   `kubectl label ns istio-system network.openshift.io/policy-group=ingress --overwrite`
   After: `https://rhods-dashboard.127.0.0.1.sslip.io/` returns 401 (reachable). (Earlier ServiceEntry/DestinationRule tls=DISABLE experiments were red herrings and were removed.)
2. **chromedriver**: Chrome 153.0.8010.36 + matching chromedriver 153.0.8010.36 (mac-arm64, chrome-for-testing) at /tmp/chromedriver.
3. **Selenium Manager cannot run in the sandbox** — the bundled `selenium-manager` binary panics on a blocked syscall (`metadata.rs:168` PermissionDenied). Fix: a fake `selenium-manager` via `SE_MANAGER_PATH` that returns the local Chrome + chromedriver paths as the expected JSON, plus a one-line patch to selenium 4.13 `get_binary()` (`SE_MANAGER_PATH` was used as a str but `path.is_file()` needs a `Path`). With this, `webdriver.Chrome()` launches (verified).
4. **Chrome sandbox**: added `--user-data-dir=/tmp/chrome-profile` (+ `--disable-crash-reporter`) to the test-variables BROWSER options (Chrome could not create a default user-data-dir under the sandbox).
5. **run_robot_test.sh Darwin bug**: line 379 `mktemp -d "${TEST_ARTIFACT_DIR}" -t ...` is invalid on macOS (TEST_ARTIFACT_DIR ends up empty and the whole run mis-parses). Fixed to `mktemp -d -p "${TEST_ARTIFACT_DIR}" ods-ci-...-XXXXXXXXXX`.

### Elyra Sanity result (ods-ci release-2.25)

The test now RUNS (driver, browser, cluster, project-namespace creation all work) but FAILS at the login step.

- Test: `Verify Pipelines Integration With Elyra When Using Standard Data Science Image` (Sanity, ODS-2197); image `Jupyter | Data Science | CPU | Python 3.12`, runtime `Runtime | Datascience | CPU | Python 3.12`.
- Result: 1 test, 1 failed. Suite Setup `Launch Data Science Project Main Page` (the OAuth login) never completed; the project was never created (`PROJECT_TO_DELETE` unset in teardown); a chromedriver crash in teardown.
- **Root cause = the 3.x dashboard auth does not support the browser login flow.** The dashboard's `kube-rbac-proxy` (port 8443 → upstream 8080) requires a valid token for **every** path including the SPA: `/`, `/index.html`, `/api`, `/healthz` all return 401 "Unauthorized". With the SPA blocked, the React app cannot load to start the OAuth dance (chicken-and-egg). The 2.x probe had `origin-oauth-proxy` performing the server-side 302-to-login + session; the 3.x probe uses `kube-rbac-proxy` (token-review based) with **no OAuth redirect layer**, so a fresh browser can never obtain a token. This is a substrate gap, not a test defect.

### Cypress (odh-dashboard v3.3.1-odh)

Would hit the **same** dashboard-auth gap (cypress e2e workbenches specs use `cy.visit(ODH_DASHBOARD_URL)` + the same OAuth login). Environment: node 20, `npm ci` at the monorepo root, `CY_TEST_CONFIG=<test-variables.yml> npm run cypress:run -- -b chrome --spec '...'` in `frontend/`; workbenches specs under `packages/cypress/cypress/tests/e2e/dataScienceProjects/workbenches/` (`workbenches.cy.ts`, `testWorkbenchControlSuite`, `testWorkbenchCreation`, `testWorkbenchImages`, `testWorkbenchStatus`, `testWorkbenchVariables`).

### Remaining substrate work to make browser tests pass

The 3.x in-kind probe needs a browser-OAuth path in front of the dashboard's kube-rbac-proxy: either (a) add an OAuth redirect layer (analogous to 2.x origin-oauth-proxy) that 302s unauthenticated browsers to the fake oauth-server, logs in, and issues a K8s token the kube-rbac-proxy accepts, or (b) configure the dashboard to serve the SPA unauthenticated so the React app drives token acquisition. Option (a) is the closer analog to the proven 2.x flow. Until then, API-token-based tests (the committed notebook-sidecar spike) pass, but browser-login-based tests (elyra, cypress e2e) fail at login.

> Note: the istio-system namespace label (gateway-routing fix) is applied only to the live cluster so far; persist it into deploy.py and re-verify after any redeploy.

## Browser-auth resolution: patched oauth-proxy sidecar (supersedes "Remaining substrate work")

Option (a) was implemented: a patched openshift/oauth-proxy sidecar in front of the dashboard's kube-rbac-proxy. The 3.x dashboard pod now has an extra oauth-proxy container (port 8443, upstream http://localhost:8446 = insecure kube-rbac-proxy).

### Source patches (/tmp/kf3x/oauth-proxy-src, upstream github.com/openshift/oauth-proxy @ bb5169e)

1. oauthproxy.go — CheckRequestAuth accepts raw Bearer tokens; Authenticate forwards Authorization: Bearer <token> to the upstream (kube-rbac-proxy does token review). This makes the proxy's session cookie (issued after browser login) work for API + websocket traffic.
2. http.go — ServeHTTPS forces NextProtos = ["http/1.1"]. Default oscrypto.SecureTLSConfig sets [h2, http/1.1]; if ALPN negotiates h2, the Go h2 response writer is not an http.Hijacker and every /wss/k8s/* websocket upgrade fails with 500.
3. logging_handler.go — the responseLogger (the -request-logging wrapper) now implements Hijack() delegating to the wrapped writer. wsutil.go:137 checks w.(http.Hijacker) and answers 500 "Not a hijacker?" (16-byte body) without it.

Build: GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build + local.Dockerfile (FROM scratch) -> quay.io/jdanek/origin-oauth-proxy:patched -> podman push -> kind load -> rollout restart deploy/rhods-dashboard.

### Final oauth-proxy args (persisted by /tmp/kf3x/patch-dashboard.py)

    -provider openshift -skip-provider-button
    -login-url https://oauth-server.127.0.0.1.sslip.io/oauth/authorize
    -upstream http://localhost:8446
    -redeem-url http://oauth-server.127.0.0.1.sslip.io/token
    -pass-access-token -request-logging
    -client-id dsh-oauth-client -client-secret dsh-oauth-secret
    -cookie-secret 0123456789abcdef0123456789abcdef
    -https-address 0.0.0.0:8443 -tls-cert ... -tls-key ...

Key gotchas:

- -redeem-url is mandatory. Without it the openshift provider discovers the token endpoint via kubernetes.default.svc/.well-known/oauth-authorization-server -> vanilla k8s API -> 403 for system:anonymous -> login callback 500 "error redeeming code". In-cluster, the http port 80 via the istio gateway works; https fails (gateway in-cluster cert "not valid for any names").
- -login-url points at the worktree oauth-server (components/oauth-server/oauth-server.go, image quay.io/jdanek/oauth-server:latest) which serves the login page, a /oauth/authorize alias, and the /token endpoint. Any username with password "password" (admin-user, ldap-admin1/2, ldap-user1/2/9).
- Fixed -cookie-secret so signed in-memory session cookies survive pod restarts.

Verified end-to-end by /tmp/kf3x/e2e-full.sh (fresh cookie jar): dashboard 302 -> login page 200 -> POST creds -> 307 callback w/ code -> redeem -> 302 -> / 200, REST /api/k8s/... 200, and /wss/k8s/... 101 Switching Protocols with live {"type":"ADDED",...} watch frames. Chrome (real browser) shows the Projects page with no "issue fetching projects" banner.

## Cypress green: testWorkbenchImages.cy.ts (v3.3.1-odh)

Invocation (verified passing, 1 passing):

    cd /tmp/odh-dashboard-3x/packages/cypress
    PATH="/tmp/kf3x/ocwrap:$PATH" KUBECONFIG=/tmp/rhoai-odh3x/.kubeconfig-probe
    CYPRESS_CACHE_FOLDER=/tmp/cypress-cache MODULE_FEDERATION_CONFIG="[]"
    BASE_URL="https://rhods-dashboard.127.0.0.1.sslip.io"
    ADMIN_USER_AUTH_TYPE="adm-auth" ADMIN_USER_USERNAME="admin-user" ADMIN_USER_PASSWORD="password"
    TEST_USER_3_AUTH_TYPE="ldap-provider-qe" TEST_USER_3_USERNAME="ldap-user2" TEST_USER_3_PASSWORD="password"
    CY_TEST_CONFIG=/tmp/kf3x/cy-test-config.yaml CY_RETRY=0
    CYPRESS_DEFAULT_COMMAND_TIMEOUT=60000
    node ../../node_modules/cypress/bin/cypress run -b chrome --spec "cypress/tests/e2e/dataScienceProjects/workbenches/testWorkbenchImages.cy.ts"

testConfig.ts maps ADMIN_USER_* -> HTPASSWD_CLUSTER_ADMIN_USER, TEST_USER_3_* -> LDAP_CONTRIBUTOR_USER; APPLICATIONS_NAMESPACE comes only from the CY_TEST_CONFIG YAML, which must also contain S3 BUCKET_1..3 keys or config crashes.

Three fixes were required beyond the auth work:

1. oc wrapper must emit clean stdout. projectChecker.verifyOpenShiftProjectExists compares "oc get project X -o name" stdout exactly against "project.project.openshift.io/X" — any extra line on stdout (e.g. a wrapper trace header) makes every verify fail with "Expected project ... to exist". The wrapper at /tmp/kf3x/ocwrap/oc logs everything to /tmp/kf3x/oc-trace.log and passes through raw oc stdout/stderr + exit code. (Also: create a wrapper via a file write, not a bash heredoc — the heredoc expands $* / $(...) at creation time.)
2. CYPRESS_DEFAULT_COMMAND_TIMEOUT=60000. Cold app start in headless Chrome on this host takes ~47s (document load -> projects/hardwareprofiles data); the 10s default made findSideBar (#page-sidebar) time out on the very first step. Warm-profile runs start in ~1s, which is why isolated debug specs looked fine.
3. s2i-minimal-notebook ImageStream was missing the opendatahub.io/notebook-image=true label that the spawner uses to filter images — the test found 10 images via oc but the UI listed only 9. Fixed with "kubectl label imagestream s2i-minimal-notebook -n redhat-ods-applications opendatahub.io/notebook-image=true --overwrite". (The worktree manifest components/08-workbenches/minimal.yaml already carries the label; the live object came from a different/newer source. The other 9 notebook streams all had it.)

## HardwareProfile (the Elyra robot blocker)

- CRD hardwareprofiles.infrastructure.opendatahub.io + a default-profile in redhat-ods-applications — worktree file components/hardware-profile/crd.yaml, applied to the cluster.
- The profile's spec.displayName (and the opendatahub.io/display-name annotation) MUST be "default-profile", not "CPU": JupyterHubSpawner.robot "Select Hardware Profile" (release-3.3, ~line 111-116) compares the disabled dropdown button text (= display-name) against the profile NAME passed by the test when only one profile exists. Run 1 failed with "Expected hardware profile 'default-profile' but found 'CPU'" because of the mismatch; run 2 passed after the rename (live object fixed via kubectl replace, manifest updated in the worktree).
- HardwareProfileSelect.tsx:255-257 renders a skeleton while the profile list is empty; with default-profile present the "Deployment size" dropdown renders "CPU".
- ods-ci Workbenches.resource (release-3.3) waits ~10s for //button[@data-testid="hardware-profile-select"] after "Deployment size" — this is what the Elyra run was failing on before the CRD/profile were applied.

## Elyra robot (ods-ci release-3.3)

Run env (all under /tmp/ods-ci-3x/ods_ci): KUBECONFIG=/tmp/rhoai-odh3x/.kubeconfig-probe, PATH with /tmp/chromedriver/chromedriver-mac-arm64, SE_MANAGER_PATH=/tmp/kf3x/fake-selenium-manager (real selenium-manager panics in the sandbox), KUBECTL_REMOTE_COMMAND_WEBSOCKETS=false, DBUS_SESSION_BUS_ADDRESS=/dev/null, POETRY_VIRTUALENVS_IN_PROJECT=true, rm -rf /tmp/chrome-profile first (Chrome can't create a default profile under the sandbox; the test-variables BROWSER options carry --user-data-dir=/tmp/chrome-profile).

## Elyra robot workbench-status blocker (run 2 -> run 3)

Run 2 got past login (ldap-user2, oauth flow), project creation, workbench creation and hardware-profile selection, then failed in "Workbench Status Should Be": the workbench never showed RUNNING within the test's 300s wait. Root cause (reproduced manually by creating a bare Notebook CR in a scratch project):

- The odh-notebook-controller (quay.io/opendatahub/odh-notebook-controller:v1.10.0-15) creates a StatefulSet with the jupyter container + a kube-rbac-proxy auth sidecar. Both images are pullable anonymously from quay.io (no internal registry: the webhook resolves the image from the ImageStream tag status dockerImageReference, e.g. quay.io/opendatahub/odh-workbench-jupyter-datascience-cpu-py312-ubi9:2025b-v1.36).
- The jupyter container cold start on this QEMU-emulated node takes ~30-50s, but the dashboard's notebook probes (frontend/src/api/k8s/notebooks.ts baseResource: liveness/readiness initialDelaySeconds=10, periodSeconds=5, failureThreshold=3) kill it after ~25s. It crash-loops (exit 137/143) several times until one cold start happens to finish inside the grace window, then the pod is 2/2 and the Notebook CR goes Ready (~5m16s end-to-end in the manual repro, lighter load than the robot run).
- The "Failed to wait for image pull secret / pull secret not mounted" log line from the controller is a benign race at creation time (it clears once the pod exists); the "policy openshift-like-volume-mounts fail: mutation is not applied" pod event is likewise pre-existing noise, not the blocker.
- Fix for in-kind: in /tmp/ods-ci-3x (ods-ci release-3.3 worktree) 0502__ide_elyra.robot Smoke test now passes workbench_timeout=900s to the test keyword (Start Workbench -> Wait Until Workbench Is Started) and its [Timeout] was raised 10m -> 20m to keep the overall budget above the worst-case start + pipeline run. No cluster-side change: on real (native) clusters the notebook starts inside the default probes and the stock timeouts hold.


## Workbench mesh-access shim: root causes and fixes (2026-09-14)

The in-kind workbench path (gateway -> wb-shim pod -> notebook KRP -> Jupyter) had two independent failure modes, both now fixed.

### 401 "Unauthorized" flapping through the gateway (the big one)

Symptom: GET /notebook/<proj>/<nb>/... via https://rhods-dashboard.127.0.0.1.sslip.io returned a mix of 200 and plain 13-byte "Unauthorized" 401s (KRP-style body, x-envoy-upstream-service-time: 0). Direct in-cluster requests to the shim svc:8445 and to the KRP svc:8443 were 100% 200 with the same token.

Root cause: the shim raw-socket bridge treated each TCP connection as a single request but left the socket open after the response. The Istio gateway reuses upstream keep-alive connections (connection pool), so subsequent requests were piped raw through the still-open pipe straight to the notebook KRP connection. Those ghost requests carried no Authorization header (only the first request per connection was rewritten by the bridge), so the KRP answered them with its standard 401, which the bridge response pipe then forwarded back to the gateway as the answer to the real request. Envoy per-host cluster stats proved it: rq_total on the shim host increased for EVERY request (including the 401s) while the shim request counter only saw the 200s.

Fix: force "Connection: close" on the upstream request (bridge.py: out.append(b"Connection: close")), so the KRP closes after each response, the bridge tears the connection down, and the gateway opens a fresh one per request. Exception: requests with an "Upgrade:" header (WebSocket, e.g. JupyterLab kernel/terminal) keep "Connection: Upgrade" instead, so WS upgrades still work. Verified: 20/20 burst 200, full cookie-jar browser simulation 200s on assets + /api/sessions|kernelspecs|contents|status.

Note: /tmp/kf3x/bridge.py is the source of truth; apply_shim_param.py base64-embeds it into every new shim pod, so future robot runs get the fix automatically.

Ruled out along the way (all verified healthy): KRP policy CM, RBAC (ldap-user2 is cluster-admin), TokenReview (30/30 in-cluster burst), shim svc selector/endpoints (exact name label, single endpoint), KRP svc DNS (single ClusterIP, stable), Envoy EDS/cluster health (single healthy host), route presence (workbench-dash-<sfx> always in the vhost, correct order above the dashboard catch-all), PeerAuthentication (mesh default PERMISSIVE; a tlsMode-istio transport_socket_match existed on the shim cluster which is why a PeerAuthentication mtls.mode=DISABLE in ns wb-shim was also added - keeps the cluster plaintext-only and stable).

### Notebook culling: controller cached the old CM

The odh-notebook-controller stops notebooks via the notebooks.opendatahub.io/stop annotation after CULL_IDLE_TIME=60m (culler config CM notebook-controller-culler-config in redhat-ods-applications). Patching the CM to ENABLE_CULLING=false had NO effect because the controller pod (created 12:58Z) had loaded the CM into memory at startup; it kept culling on schedule (the 7489 notebook stopped exactly 60m after start). Fix: kubectl rollout restart deploy/odh-notebook-controller-manager -n redhat-ods-applications (re-reads the CM with ENABLE_CULLING=false). If the notebook was already stopped, restart it with: kubectl annotate notebook elyrajupyter-data-science-cpu -n <proj> notebooks.opendatahub.io/stop- kubeflow-resource-stopped-

### Robot suite-setup string (ODHDashboard.robot line 86)

Upstream release-3.3 code contains a CI-template artifact: Create List    Log in with    Data Sciencapodhrad-gcp-pool-gtcd5e Projects (a GCP node-pool name baked into the "already logged in" expected string). With a warm Chrome profile the browser is already logged in, the page shows plain "Data Science Projects", neither string matches, and the whole suite setup fails after 12 retries. Fixed locally: the second string is now "Data Science Projects" (matches the real page; "Log in with" still covers the fresh-login case).

### Robot invocation (unchanged, verified working)

    cd /tmp/ods-ci-3x/ods_ci
    ./run_robot_test.sh --test-case tests/Tests/0500__ide/0502__ide_elyra.robot --include Smoke --skip-oclogin true

### Cluster state changes this session

- PeerAuthentication disable-mtls (ns wb-shim, mtls.mode=DISABLE) created - keeps wb-shim clusters plaintext.
- odh-notebook-controller-manager restarted (re-read culler CM, ENABLE_CULLING=false now honored).
- Leftover namespaces elyra-test-8132 / elyra-test-9488 deleted (their workbench-dash-<sfx> routes are gone from the gateway).
- Scratch pods in default ns cleaned up.

## Session 3: Elyra pipeline run green (dspa UI sim, kernel timeout, probe hardening)

Goal: `0502__ide_elyra.robot` Smoke (create workbench -> Elyra -> run hello-world pipeline -> verify run completed) passing in-kind.

### dspa host serves no UI - dashboard-proxy shim (v3)

The real dspa host (ds-pipeline-dspa-<proj>.apps.127.0.0.1.sslip.io) is the ODH dashboard app scoped to the Pipelines section (same #page-sidebar, Experiments, topology views); the in-kind dspa KRP serves only the REST API, so the robot "Run Details." flow had no UI.

- /tmp/kf3x/dspabridge.py (v3): proxies ALL traffic to http://rhods-dashboard.redhat-ods-applications.svc.cluster.local:8447 (the dashboard "plain" frontend port, per the rhods-dashboard HTTPRoute backend) with Authorization: Bearer <token> injected; GET /<exp>/runs/<run-id> with Accept: text/html additionally fetches the run (dspa REST /apis/v2beta1/runs/<id>) and injects a banner div with display_name + state into the SPA shell before </body> (satisfies the robot's "Wait Until Page Contains <run name>").
- The shim pod/svc/ReferenceGrant must live in redhat-ods-applications: the dashboard NetworkPolicy (rhods-dashboard-allow-ports) only allows the gateway ns (network.openshift.io/policy-group=ingress) and same-namespace pods; dspa KRP NP allows from=null (anyone) on 8443. A shim in wb-shim can reach the KRP but NOT the dashboard (verified: timeouts from default/wb-shim ns pods).
- Route patch: merge-patch the ds-pipeline-dspa HTTPRoute backendRefs to the shim svc (port 8445). Route hostnames are the .apps. variant - the browser uses exactly that (the Elyra "Run Details." link URL comes from the dspa server config). The dspa operator creates the route seconds-to-minutes after dspa deploys (QEMU), so /tmp/kf3x/dspa_route_patch.py retries (48x10s) as a DETACHED worker (subprocess.Popen start_new_session; daemon threads die with the applier).
- Verified live: 200 SPA shell + /api/health {"health":"ok"} + banner with run name through the gateway.

### papermill kernel timeout: start_timeout (not startup_timeout)

- "Kernel didn't respond in 60 seconds" persisted after patching startup_timeout: papermill 2.6.0 engine signature takes start_timeout (passed to nbclient start_new_kernel_client) and **kwargs; startup_timeout is silently dropped. Correct patch: bootstrapper.py line 374 kwargs = {"start_timeout": 900, "kernel_timeout": 900}.
- 900s is needed because the QEMU load during a run (workbench jupyter + pipeline step + chrome) can stall kernel start past 300s (observed: 300s timeout tripped in run 28; idle node measures import ipykernel at 1.2s).
- Mitigation for the load: Stop Workbench Via K8s (kubectl delete notebooks -n <proj>) right after the pipeline is submitted - all later steps are dashboard-side. Teardown stop made conditional (only if running/starting) so an already-stopped workbench does not fail teardown.
- Image workflow: docker build --platform=linux/amd64 -f runtime-patched.Dockerfile (FROM base, COPY bootstrapper to /opt/app-root/bin/utils/bootstrapper.py), tag BOTH quay.io/jdanek/...:2025b-patched and quay.io/opendatahub/...:2025b-v1.36; docker save; import into the kind node via docker cp <tar> kind-control-plane:/tmp/... + ctr -n k8s.io images import --all-platforms <file> (docker exec -i ... < tar stdin redirect fails in this sandbox; ctr import of a jdanek-tagged tar leaves the opendatahub tag stale - ctr -n k8s.io images tag <jdanek-ref> <odh-ref>). Verify: crictl images digest + in-pod grep of the bootstrapper.

### Workbench liveness kills under QEMU load

- Root cause of runs 17-27 UI flakiness: kubelet liveness probe on jupyter (http :8888/notebook/<proj>/<nb>/api) got transient connection-refused under QEMU CPU spikes -> Killing notebook pod. Pod events show the Liveness probe failed -> Killing chain.
- Fix: /tmp/kf3x/harden_probes.py - get Notebook CR (notebooks.kubeflow.org), set every container probe to timeoutSeconds=15/periodSeconds=30/failureThreshold=10, kubectl replace (strip resourceVersion/status, empty managedFields), delete the pod by -l notebook-name=<nb> (label IS present on ODH 3.x workbench pods) with a name-match fallback; workbench_ready.py waits for the (recycled) pod to be Running+ready (by name substring elyrajupyter, label-independent). Called as Harden Workbench Probes between the two Start Workbench phases; verified in run 28 (PROBES-HARDENED, pod recycled, pipeline ran).

### Robot Framework / shell gotchas

- Run/Run And Return Rc And Output expands %{NAME} as env vars: curl -w %{http_code} must be -w %25{http_code}; a command string containing a variable with spaces/pipes (workbench titles like "elyra_Jupyter | Data Science | CPU | Python 3.12") breaks sh -c (pipes execute!) - prefer a small python helper polled via Run over inline curl with unquoted URLs (wb_poll.py).
- Run And Return Rc And Output returns TWO values (rc, output) - needs two LHS vars.
- Menu.robot Navigate To Page default timeout raised 10s -> 60s; Elyra.resource Save Pipeline Changes retries 3x20s on the "Saving completed" toast.
- Non-fatal warnings in every run (ignore): "Log in with OpenShift did not appear in 15 seconds", "Cloning... did not appear in 5 seconds", "No Modals on the screen".

### Cluster state changes this session

- dspa shim pods/svcs/ReferenceGrants in redhat-ods-applications (dspa-shim-<sfx>, deleted with the project where the applier cleaned up; 0362's removed manually).
- wb-shim pods for each run's project (workbench-dash-<sfx> routes on the dashboard host).
- Node: runtime image quay.io/opendatahub/...:2025b-v1.36 re-imported as the 900s-patched build (manifest 1821baad...); host /tmp/kf3x/runtime-patched*.tar (3.2GB each - delete after verifying).
- Notebook CRs in test projects: probes hardened (timeout 15s / period 30s / failures 10).


## Session 4 — Elyra→dspa chain root-caused; full E2E verified manually

### The Elyra pipeline run path (critical architecture fact)
The Elyra frontend does NOT call the dspa host directly. All KFP traffic goes
through the workbench Jupyter server's elyra extension:
browser -> POST .../notebook/<proj>/<nb>/elyra/pipeline/... (jupyter-lab:8888)
-> elyra python backend (site-packages/elyra/pipeline/handlers.py, kfp/processor_kfp.py)
-> kfp ArgoClient against the "odh_dsp" runtime config endpoint, which the
dashboard registers as the ROUTE URL: https://ds-pipeline-dspa-<proj>.apps.127.0.0.1.sslip.io
So the in-pod client must (a) resolve the .apps. host (it resolves to the gateway
ClusterIP 10.96.x.x via in-cluster DNS) and (b) verify the gateway TLS cert.

### TLS trust requirement
The pod trusts /var/run/secrets/kubernetes.io/serviceaccount/combined-ca-bundle.crt
(the platform already sets SSL_CERT_FILE to it — do not fight it). Steady state:
the istio Gateway (istio-system, 443 Terminate) references sslip-tls-secret in
cert-manager ns; that leaf (CN=*.apps.127.0.0.1.sslip.io) is signed by
"My Cluster CA", which IS in the combined bundle -> strict TLS from pods works.
TRANSIENT BAD STATE (caused run 34): gateway presents a cert NOT signed by My
Cluster CA -> kfp client healthz fails CERTIFICATE_VERIFY_FAILED -> run POST 500
-> "Run Details." link never appears (no console errors, no dspa-side trace).
Diagnosis recipe: kubectl logs <workbench-pod> | grep -B2 -A20 ArgoClient
(the final line names the endpoint + SSL error + kfp TIP).
Verified manually (2026-09-15 ~06:00Z): pod python TLS to the dspa route host
works (401 without token = reached KRP); full E2E in real Chrome succeeded:
Elyra Run Pipeline -> Ok -> toast "Job submission to Data Science Pipelines
succeeded" + "Run Details." link (URL shape /<exp-uuid>/runs/<run-uuid>) and
the argo workflow started Running.

### dspabridge v4 (hybrid) — /tmp/kf3x/dspabridge.py
- /apis/* -> proxy to the real dspa KRP (https upstream, token injected) — needed
  for any client that does hit the route host (browser JS in other flows, KFP).
- GET */runs/<id> with Accept text/html -> dashboard SPA shell (fetched ONCE,
  cached; minimal inline fallback on total failure) + banner div with
  display_name/state from dspa REST. RUN_RE = /runs/([^/?#]+) (search, not
  anchored — real URL has a uuid segment before /runs/).
- everything else -> dashboard 8447 with token.
Verified in-cluster: /apis/v2beta1/runs 200 via sim; / -> 628B SPA; run page =
628B SPA + 130B banner (the robot's sidebar navigation works off the real SPA).

### Suite-setup blockers fixed (runs 31-34 all died here or at run submit)
1. NEW project ns has NO openshift-service-ca.crt ConfigMap -> dspa operator
   stuck (all conditions Unknown, 0 pods, "ConfigMap openshift-service-ca.crt
   not found" retry loop). The service-ca operator is broken in this cluster
   (no openshift-config-managed ns). Fix: 0502 suite setup seeds the CM from
   the default ns (helper /tmp/kf3x/service_ca_cm.py <proj>).
2. DataSciencePipelinesBackend "Wait Until Pipeline Server Is Deployed" bumped
   15x10s -> 40x10s (QEMU pod startup under load). Check needs >=7 pods with
   label component=data-science-pipelines (steady state is exactly 7).
3. Stale test projects must be deleted between runs — each carries ~7 dspa
   pods + workbench that hammer the QEMU node (6 stale projects nearly
   starved a fresh suite setup).

### Workbench stop (in-kind)
kubectl delete notebooks does NOT stop an ODH 3.x workbench (pod keeps
running). The dashboard stop = add annotation kubeflow-resource-stopped=<UTC ts>
to the Notebook CR (CR stays, pod deleted, UI shows Stopped); start = remove
annotation. Helper /tmp/kf3x/workbench_stop.py <proj> (annotate + wait for no
elyrajupyter pods, 30x10s). CRD group/version = kubeflow.org/v1 (NOT
notebook.kubeflow.org/v1). The 0502 keyword "Stop Workbench Via K8s" now calls
this helper. CR replace pattern: strip resourceVersion + status,
managedFields=[] (else Conflict against the controller).

### 0502 run-name wait
Line ~127: Wait Until Page Contains <run name> timeout 120s -> 5m (QEMU).

### chrome-mcp usage notes (for future in-kind browser work)
- ALL mcp__chrome-mcp__* calls require explicit pageId (no implicit selection).
- evaluate_script: pass "function" as a function-expression string (fn body is
  auto-invoked); IIFEs fail ("fn is not a function").
- Cert bypass for self-signed hosts: open the URL (hits ERR_CERT_AUTHORITY_
  INVALID / chrome-error page), then type "thisisunsafe" while the error page
  is focused (press_key/type_text with the pageId) — page proceeds.
- Never touch the user's existing tabs: new_page for work, close_page at end.
- Network capture: install a fetch/XHR interceptor via evaluate_script AFTER
  final navigation (navigation wipes it); SPA-internal clicks keep it.
- Elyra pipeline editor opens directly at .../lab/tree/<clone>/<file>.pipeline
  (same URL the robot uses); toolbar has Run Pipeline / Save Pipeline buttons.

### Run 35
First run with the complete stack: v4 sim + service-CA seeding + 40x10s suite
wait + annotation stop + 900s kernel image + probe hardening + 5m run-name
wait, on a clean node. Watch for: gateway cert transient (ArgoClient SSL in
workbench pod logs) if run submit 500s again.


### Route revert + persistent guard (run 35 follow-up)
The dspa operator re-applies the ds-pipeline-dspa HTTPRoute on every reconcile,
SILENTLY reverting the one-shot merge-patch that points the route at the dspa
sim. The in-repo background re-patcher (dspa_route_patch.py, Popen'd from the
host during provisioning) exits after the first successful patch and dies with
the robot run, so the revert wins later. Consequence: the Elyra run itself can
succeed (it goes through the route while it is still patched) but the later
"Run Details." navigation 401s (dashboard proxy, no browser cookie for the
dspa host).
Fix: /tmp/kf3x/dspa_sim_guard.py <proj> (in 0502 suite setup, right after the
dspa deploy wait):
- SA token for ldap-user2 (8h) as the sim's injected token
- dspa-shim-<sfx> pod (v4) + svc + ReferenceGrant in redhat-ods-applications
- PERSISTENT guard pod dspa-route-guard-<sfx> IN the project namespace with its
  own SA (Role: httproutes get/list/watch/patch in the project) that every 10s
  checks the route and re-patches backendRefs to the sim via the k8s REST API
  (verified: manual revert of the route is auto-repaired within ~10s)
- 48x10s retry until the operator has created the route
Teardown: /tmp/kf3x/dspa_sim_cleanup.py <proj> deletes the sim pod/svc/
ReferenceGrant from redhat-ods-applications (they survive project deletion).
Run-page verified end-to-end in real Chrome: 200, banner
"Pipeline run: <b>hello-generic-world-0915043353</b> - State: RUNNING".
Note: the robot's browser has no cookie for the dspa host (dashboard cookie is
host-only) — the sim's run-page branch is server-side rendered (its own token),
so the banner works without any browser session on the dspa host.

### Token anatomy (in-kind)
Robot "users" map to K8s SAs: ldap-user2 -> system:serviceaccount:oauth-server:
ldap-user2. fetch_token.py's /token output is NOT a usable JWT (dspa 401s on
it) — use kubectl create token <sa> -n oauth-server --duration=8h instead
(dspa accepts these SA tokens directly).
TLS monitor (in-pod, 2s interval, 22 min): 675/675 OK — the gateway TLS flap
behind run 35 did not recur spontaneously; the run-retry in 0502 covers the
churn window anyway.

### Run 37 post-mortem: failed Elyra submission leaves the Run dialog open
When the Elyra run submission fails on the client side (gateway TLS flap window,
~05:35 UTC in run 37 — the dspa operator was in an ArgoWorkflowsControllersConfig
"cannot unmarshal string" error loop at 05:13, i.e. active reconcile churn), the
Run Pipeline DIALOG stays open (no success toast, no Run Details link). The retry
loop's second click is then blocked with ElementClickInterceptedException
(other element: <dialog aria-modal class="jp-Dialog">). Fixes in 0502:
- 4 attempts, 90s backoff (flap windows last minutes)
- Press Key Escape (body) before each attempt to close a leftover dialog
- on failure: log the open dialog's innerText (Execute JavaScript) + Capture
  Screenshot elyra-run-attempt-N-failed for diagnosis
Also dspa_sim_guard.py now CREATES the ds-pipeline-dspa HTTPRoute itself when the
operator has not created it yet (under QEMU the operator lags 15-20+ min, run 36
died on DSPAROUTE-UNPATCHED at the 8-min mark); the patch loop is now 40x15s.

### Runs 39-41: kfp.Client() init failures + the dialog-close saga
- Run 39/38: Press Key arg-count issues in this SeleniumLibrary; replaced with
  native <dialog>.close() via Execute JavaScript.
- Run 40: first Elyra attempt failed with the dialog state captured (the new
  diagnostic works): "Failed to initialize kfp.Client() against
  https://ds-pipeline-dspa-<proj>.apps.127.0.0.1.sslip.io ... Check Kubeflow
  Pipelines runtime configuration: 'odh_dsp'". The test then died on a bad
  'Capture Screenshot' keyword name (now SeleniumLibrary.Capture Page Screenshot)
  instead of retrying.
- Run 41: attempt 0 failed the same way (kfp.Client init); the leftover dialog
  was closed by the JS, but a NEW dialog appeared before attempt 1 (suspected
  jupyter reconnect dialog after a probe kill under QEMU) and intercepted the
  click. Now: before each attempt, Wait Until Page Does Not Contain Element
  //dialog[@aria-modal=true] (up to 12x5s); after a failed attempt, capture the
  workbench pod's logs (kubectl logs --all-containers) + screenshot.
- Cold-start hypothesis for the kfp.Client init failures: in runs 40/41 the
  submission happened 3-8 min after the dspa deployments were Ready, while the
  successful manual 6217 run used a dspa warm for hours. The dspa api-server
  can take minutes to serve KFP requests after Ready. dspa_sim_guard.py now
  warms the endpoint (curl /apis/v2beta1/experiments through gateway+sim, the
  same path Elyra uses) up to 15 min before the test starts; the 4-attempt
  retry with 90s backoff covers the rest.

### RUN 46 BREAKTHROUGH: root cause found and fixed
- Run 46 was launched with the dspa operator SCALED DOWN during the test
  (suite setup: scale 1 -> deploy pipeline server -> sim/guard -> scale 0;
  suite teardown: scale 1 + rollout status BEFORE project deletion, because the
  dspa CR finalizer only the operator can remove).
- Result: **the Elyra run was submitted successfully for the first time in the
  robot** - the Run dialog Ok click at 10:18:38 produced the Run Details link
  (${run_ok} = True) with zero kfp.Client() init failures. The operator
  scale-down eliminated the gateway cert flap.
- The failure then moved to the NEXT step: Menu.Navigate To Page's
  //div[@id="page-sidebar"] wait (60s default) was too short under QEMU after
  the workbench stop. Fixed: timeout=3m on that one call in the test.
- Secondary systematic bug found: 'Delete Project Via CLI By Display Name'
  reports "Project not found, or not a user-defined Data Science project" in
  in-kind and leaves the namespace Active with all 7-9 dspa pods running
  (memory pressure on QEMU). Fixed: suite teardown now also runs
  'kubectl delete ns <project> --wait=false --ignore-not-found' after the CLI
  delete (operator already restored, so the finalizer processes).
- The full failure chain, now fully explained:
  1. dspa operator re-applies the ds-pipeline-dspa HTTPRoute on each reconcile
     (project deploy churn: component readiness transitions, ArgoWorkflowsControllersConfig
     unmarshal errors at CR creation).
  2. Each route re-apply = xDS push to the istio gateway.
  3. During xDS reconfiguration the gateway transiently serves a FALLBACK cert to
     in-cluster (mTLS sidecar) clients - the pod's strict TLS verify fails:
     'CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate' on
     /apis/v2beta1/healthz (captured live from the jupyter log in run 45).
  4. Host-side curl -k never sees it (passthrough path, no verify).
  5. Elyra backend kfp.Client() init fails, Run dialog stays open, retries blocked.
  6. With the operator scaled down during the test there is no route churn, no
     xDS pushes, no flaps: a 15-min in-pod TLS monitor on an idle cluster showed
     428/428 OK, and run 46's submission went through clean.
- dspa CR: spec has apiServer/database/dspVersion/objectStorage/persistenceAgent/
  podToPodTLS/scheduledWorkflow - NO argoWorkflowsControllersConfig field; the
  unmarshal error comes from somewhere else in the operator's reconcile and is
  bursty (zero occurrences in a 40-min idle window).
- Remaining risk for the green run: Verify Pipeline Run Is Completed (20m) -
  the argo workflow (run by the in-project ds-pipeline-workflow-controller-dspa
  pod, unaffected by the operator scale-down) must actually complete.

### Runs 49-52: the real root cause - the pod CA bundle
- Run 46 proved the operator scale-down removes the dspa-operator churn; runs 47-48
  still failed with CERTIFICATE_VERIFY_FAILED even with the operator down.
- Run 49/50: TLS gate (strict in-pod probe before each attempt) added; two RF
  syntax bugs fixed (IF 'contains' operator not allowed; var must be inside the
  string literal; gate now emits GATEPASS/GATEFAIL tokens + Strip String).
- Run 51 is the decisive one: the in-pod probe showed
  POD-TLS-FAIL while openssl s_client from the same pod received the CORRECT
  leaf (issuer=CN=My Cluster CA, fingerprint C8:BB:EE:87... = the stable leaf),
  and the host-side strict probe (same SNI, sslip CA) showed HOST-TLS-OK.
  => The gateway presents the right cert; the POD's CA bundle
  (/var/run/secrets/.../combined-ca-bundle.crt) cannot verify it: the istio
  gateway CA is missing from the pod trust store. The in-kind service-ca
  operator is broken and the default-ns openshift-service-ca.crt CM is EMPTY
  (0 bytes), so the platform-assembled bundle lacks the gateway CA.
- Fixes in run 52:
  1. service_ca_cm.py now appends the istio CA (cert-manager/sslip-tls-secret
     ca.crt) to the per-project openshift-service-ca.crt CM before the
     workbench pod is created (new pods get it in the bundle).
  2. One-time 'openssl verify -CAfile <bundle> <leaf>' + BUNDLE-CERTS count
     diagnostic per attempt (definitive bundle evidence).
  3. Gate fallback: after 2 GATEFAILs the istio CA is appended live into the
     pod's bundle (kubectl exec -i ... 'grep -q "My Cluster CA" || cat >>'
     < /tmp/kf3x/sslipca.pem) - idempotent, no-op if the mount is read-only.
- Other run-48/51 findings: the 'Cloning...' 5s WARN in Clone Git Repository
  And Open is benign (wrapped in Warn/Ignore, flow continues); the
  '//form[elyra-dialog-form] did not appear in 5s' failure in run 48 was the
  same clone phase, not the Run dialog.
- Run 46 also fixed: Menu.Navigate To Page 3m timeout (dashboard sidebar under
  QEMU); suite teardown now kubectl-deletes the project ns (the CLI delete
  misses the project by display name and leaves the ns + 7-9 pods behind).
- Test timeout raised 45m -> 60m (gate waits + pipeline completion headroom).

### Run 54 root cause: the dspa operator pod lost its CA bundle
- Run 54 failed in suite setup: Create Pipeline Server passed, but the dspa
  deployment never appeared (40x10s wait). Operator logs showed an infinite
  reconcile loop: "Encountered error when parsing CR: [open
  /var/run/secrets/kubernetes.io/serviceaccount/combined-ca-bundle.crt: no such
  file or directory]" for the run-54 project.
- The operator pod (recreated by run 53's teardown scale-up at ~12:52) had NO
  combined-ca-bundle.crt in its SA volume. The in-kind platform injects that
  file into pod SA volumes only when the namespace carries the
  rhoai-in-kind.io/inject-openshift-ca label AND has an
  odh-trusted-ca-bundle ConfigMap. A platform re-sync (~12:0x, CMs are 52-60m
  old) recreated the CM in most namespaces but MISSED redhat-ods-applications.
  The old 2-day operator pod (created before the re-sync) had the file, which is
  why runs 40-53 deployed dspa fine.
- Fix: /tmp/kf3x/operator_ca_fix.py (suite setup step): ensure the CM exists in
  redhat-ods-applications (copy from default ns, kubectl create - not apply,
  the 262KB last-applied annotation overflows) and verify the running operator
  pod has the file (restart the pod when missing). Idempotent; verified the new
  pod got combined-ca-bundle.crt.
- Bundle contents: odh-trusted-ca-bundle = 158 PUBLIC CAs (DigiCert, Amazon,
  ...). The istio "My Cluster CA" (fingerprint 81:08:E8:8F...) is NOT in it.
  The workbench pods' combined-ca-bundle (159 certs in the 6217 era = 158 + 1
  from the ns openshift-service-ca.crt CM) therefore gains the gateway CA only
  through the service-CA CM - which is exactly what the extended
  service_ca_cm.py now seeds (istio CA appended per project). The live
  bundle-append fallback in the run gate covers the case where the operator
  overwrites the project CM mid-run.
- Also: the 'default' ns openshift-service-ca.crt CM ca-bundle.crt is EMPTY
  (0 bytes, managed by service-ca-operator) - the original seeder copied an
  empty bundle; the new seeder adds the istio CA itself.
- Stale ns dsp-wb-test-911610 (empty, pre-robot era) deleted.
- Run 52/53 also hit a JupyterLab Git-menu flake in Clone Git Repository And
  Open (the 'Clone a Repository' menu item click misses under QEMU; the
  library keyword is in an installed lib and hard-fails). Fix: in-test retry -
  (a) if the repo file is already in the file browser, just open it;
  (b) otherwise use the new 'In-Kind Clone Repo And Open' keyword which
  retries the menu open up to 3x (10s) and waits 30s for 'Cloning...'.

### Run 55/56 root causes + controller probe hardening
- Run 55: probe hardening hit a one-shot resourceVersion Conflict on the
  Notebook CR (the notebook controller reconciles continuously). Fix:
  harden_probes.py now retries the get-modify-replace cycle up to 6x (5s)
  and is idempotent (skips already-hardened probes).
- Run 56: the workbench pod never reached Running in 15 min (stuck
  ContainerCreating/Pending; storage stack healthy, no stuck PVs). The
  odh-notebook-controller-manager pod showed liveness probe failures at
  that time: its probes are timeoutSeconds=1/failureThreshold=3 - too
  strict under QEMU (3x1s misses = kubelet kill = workbench management
  outage). Fix: patched odh-notebook-controller-manager AND
  data-science-pipelines-operator-controller-manager deployments:
  liveness/readiness timeoutSeconds=10, failureThreshold=6 (probe files
  /tmp/kf3x/nbc-patch.json, dspaop-patch.json; both rolled out). These
  deployment patches persist across pod restarts.
- Smoke test case: workbench_timeout 900s -> 1800s, test [Timeout] 60m ->
  90m (QEMU headroom).
- Run 55 also proved the operator CA fix works: the pipeline server
  deployed (runs 40-55 pattern restored) - the dspa CR parsed fine.

### Run 57: workbench liveness crash-loop + Elyra canvas render timeout
- Run 57 workbench pod crash-looped during Start: the STOCK workbench
  probes (liveness timeoutSeconds=1, periodSeconds=5, failureThreshold=3,
  initialDelaySeconds=10) kill the jupyter container while it is still
  booting under QEMU (container lived ~52s per cycle, exit 137, 7 restarts).
  The Harden Workbench Probes step ran AFTER Start, so the first pod always
  died. This is also what made run 56's workbench NotReady for 15 min.
- Fixes:
  1. Test flow: Harden Workbench Probes moved BEFORE Start Workbench (the
     first pod is born with tolerant probes; the recycle is a no-op while
     stopped).
  2. Live rescue of run 57: ran harden_probes.py on the running project
     (PROBES-HARDENED), the fresh pod reached 2/2 Running with 0 restarts.
- Run 57 then died at Verify Hello World Pipeline Elements: the Elyra SVG
  canvas did not render in the stock 10s wait (jupyter server had just gone
  through the crash-loop; canvas render under QEMU is variable). The run
  block itself was NOT RUN (verified in output.xml: FOR body keywords have
  status NOT RUN). Fix: SVG canvas wait 10s -> 2m in that keyword.
- The 'Stopped did not appear in 10 seconds' msg in run 57's output is the
  benign Start Workbench pre-check (Run Keyword And Continue On Failure),
  not the failure.


### Run 58: workbench healthy, Elyra run dialog 5s wait too strict
- With hardening BEFORE start, the workbench pod was 2/2 Running 0-restarts
  the whole run (no crash loop). The seeder put the istio CA in the project
  service-CA CM before pod creation, so the gate passed on the FIRST probe
  (GATEPASS 16:14:43, no live-append needed).
- Clone retry path used (standard clone missed the menu; "already cloned"
  direct open worked).
- Fatal: stock Run Pipeline (Click Run Button, then Wait Until Page Contains
  Element ELYRA_DIALOG with the default 5s timeout) failed at 16:19:25: the
  Elyra run dialog did not render within 5s under QEMU. Because Run Pipeline
  is a hard keyword call, the test aborted BEFORE the 4-attempt retry could
  act.
- Fix: inlined the Run Pipeline sequence in the test attempt body with a 60s
  dialog wait; on dialog-open failure it logs the dialog state, captures a
  screenshot, sleeps 30s and CONTINUEs to the next attempt. Set Pipeline
  Name / Select Runtime Config / Click Ok follow the tolerant wait.


### Run 59: workbench pod had NO combined-ca-bundle.crt at all
- The 60s dialog wait worked (attempts 1-3 retried cleanly; the dialog never
  re-opened after attempt 0's backend error, which is the expected Elyra
  state after a failed kfp.Client init).
- Decisive evidence: in-pod "pod CA-bundle verify" reported
  "No such file or directory" for
  /var/run/secrets/kubernetes.io/serviceaccount/combined-ca-bundle.crt, and
  the live CA append (gate_i==2) also hit "No such file or directory" (rc=1).
  The gateway served the correct leaf (My Cluster CA, fp C8:BB:EE:87...8E)
  and the host-side strict probe passed (HOST-TLS-OK) - only the pod path
  was broken because the file did not exist in the pod's SA volume.
- Mechanism: the platform injects combined-ca-bundle.crt into a pod's SA
  volume only when the namespace has BOTH the label
  rhoai-in-kind.io/inject-openshift-ca=true AND the ns
  odh-trusted-ca-bundle ConfigMap. The label was present, but the CM
  injection is racy under in-kind re-syncs: run 58's ns (elyra-test-2527)
  had the CM (gate GATEPASS on the first probe), run 59's ns
  (elyra-test-4731) did not (gate GATEFAIL for all 6 iterations of every
  attempt, Elyra backend kfp.Client init failed with the request error).
- Fix: service_ca_cm.py now also creates the odh-trusted-ca-bundle CM in the
  project ns right after project creation (copied from the default ns,
  kubectl create because the 487KB doc overflows the last-applied
  annotation limit; idempotent, prints TRUSTED-BUNDLE-CREATED/EXISTS).
  The CM now provably exists before the workbench pod is created, so the
  combined bundle (158 public CAs + istio gateway CA from the service-CA
  CM) is present from pod birth - same state as run 58.


### Run 60: full chain works; final cold-SPA navigation 3m too strict
- TRUSTED-BUNDLE-CREATED in the new project ns at suite setup (17:44:55);
  the workbench pod's combined bundle then contained the istio gateway CA
  from birth: gate GATEPASS on the FIRST probe (17:49:40). No live-append
  fallback needed.
- Clone retry path, 2m canvas wait, 60s run-dialog wait all worked; the
  Elyra run SUBMITTED successfully and the Run Details link + run name were
  validated (17:50:45). This is the deepest success to date.
- Fatal (last step): Menu.Navigate To Page -> Pipeline definitions timed
  out at 3m: the dashboard SPA cold load (sidebar) right after leaving the
  dspa run page exceeded 3m under QEMU. Fix: that navigation timeout 3m ->
  6m. The only steps after it are Select Pipeline Project By Name and
  Verify Pipeline Run Is Completed (20m), and the dspa run had already
  started, so the next run should be able to complete.


### Run 61: final navigation failed in the WRONG window (not just slow)
- Same symptom as run 60 (page-sidebar timeout, now at 6m) -> root cause:
  Menu.Navigate To Page does NOT navigate; it only waits for the dashboard
  sidebar in the CURRENT window. After Switch To Pipeline Execution Page
  the current window is the dspa run page (a NEW window). In OpenShift CI
  that page is the dashboard's own pipeline-run UI (sidebar present), but
  in-kind it is the simulated dspa run page (no sidebar) -> the wait can
  never succeed regardless of timeout.
- Fix: capture Get Window Identifiers before switching (dashboard =
  window_ids[0], created first), then Switch Window back to it after the
  dspa run-name validation, before Menu.Navigate To Page.
- Runs 60/61 also proved the whole submission chain end to end (gate
  GATEPASS first probe, run submitted, Run Details + run name validated).


### Run 62: deepest success yet - final completion wait (Succeeded) timed out
- The window-switch fix worked: after the dspa run-name validation the test
  switched back to the dashboard window, navigated to Pipeline definitions,
  selected the project and opened the run detail (all inside one 18-min run).
- Fatal: Verify Pipeline Run Is Completed waited 20m for the 'Succeeded'
  status label and it never appeared. First in-kind run to actually reach
  completion verification - the real Argo workflow (emulated amd64 pods on
  QEMU) either did not finish in 20m or failed/stuck (ns destroyed by
  teardown, no live evidence left).
- Fix: one-shot dspa_run_probe.py (workflows + pods + events) logged into
  output.xml right before the completion wait, and the wait raised 20m ->
  30m. Run 63 will show the actual workflow/pod state.


### Run 62/63: pipeline run FAILED at load-weather-data - node-VM OOM (root cause found)
- Run 62 reached the very last verification (Succeeded wait, 20m) and timed
  out. Screenshots (read by an image-capable subagent) showed the run detail
  page at the end of the wait: run status badge "Failed", step
  load-weather-data red, downstream notebooks not run.
- Run 63 reproduced it live: the KFP step pod
  (standard-data-science-pipeline-...-metadata-3-5-system-container-impl-...)
  ran papermill; the ipykernel went silent and papermill aborted after
  "Kernel didn't respond in 900 seconds" -> step Failed -> run Failed.
- Ruled out: network egress (the pod downloads the 3.5MB noaa-weather
  tarball from raw.githubusercontent.com in 0.8s, DNS + HTTP verified from
  the SAME runtime image), IPv6 (cluster is IPv4-only), pod memory limits
  (step pod has none, Burstable, memory request 0).
- Root cause: the node Docker VM (16GB, NO swap) is exhausted at pipeline
  time. The KFP runtime image is x86_64 -> every pipeline process
  (launcher-v2, papermill, ipykernel) runs under QEMU user-mode emulation
  with large RSS. Platform baseline (kube-apiserver bloated to 2GB, argocd,
  kyverno, istio, ODH, dspa, mariadb) + emulated pipeline pods > 16GB ->
  global OOM killer picks the step-pod cgroup (50 OOM events in dmesg;
  "Killed process ... (launcher-v2)" with CONSTRAINT_MEMCG) -> kernel dies
  -> 900s papermill timeout.
- Fixes applied for run 64:
  1. kube-apiserver restarted (2GB -> 1.3GB, +700MB reclaimed; API healthy).
  2. Test now scales argocd (6 deploys) + kyverno (4 deploys) to 0 after
     Stop Workbench Via K8s and restores them in the teardown
     (In-Kind Reduce/Restore Platform Load keywords), ~1-1.5GB freed for
     the pipeline wait.
  3. Completion wait raised to 30m + background Argo probe loop
     (15x120s to /tmp/kf3x/dspa_run_probe.txt, logged by teardown) so any
     future failure leaves workflow/pod/event evidence.
- Open: if the OOM recurs even with the scale-down, options are raising the
  Docker Desktop VM memory (needs Docker restart -> cluster loss) or a
  run-retry (re-run the pipeline from the still-open Elyra editor after a
  Failed run).


### Run 64: scale-down helped memory, but the real blocker surfaced - Rosetta 2
- The argocd (6 deploys + application-controller statefulset) + kyverno (4
  deploys) scale-down during the pipeline wait worked (MemAvailable ~9.5GB
  the whole run; the apiserver restart reclaimed ~700MB). No OOM this time.
- The workflow still failed at 16m at load-weather-data with the same
  "Kernel didn't respond in 900 seconds" - now traced to kernel STARTUP
  (papermill setup_kernel -> wait_for_ready never completes), not a cell.
- Emulator identity: the node VM has NO qemu-x86_64 binfmt handler and no
  qemu binaries. All x86_64 processes run through the binfmt entry
  "rosetta" -> interpreter /mnt/rosetta: Docker Desktop's Apple Rosetta 2
  (api-extension, oauth-server, service-ca-operator, node, the ODH
  operators... all under Rosetta, and they work fine).
- Isolation tests (pod with the runtime image, default ns):
  - raw pyzmq REQ/REP loopback roundtrip: OK in 0.0s
  - ipykernel manual launch: process starts, logs "Heartbeat REP Channel
    on port", but the client ready-handshake (kernel_info on the shell
    port) never completes - same in a minimal jupyter_client
    KernelManager.wait_for_ready (600s, no ready, no timeout exception
    surfaced)
  - CONTROL: the same KernelManager test in a native aarch64 jupyter
    image: kernel READY + execute in seconds.
- So: Jupyter kernels (ipykernel) cannot complete the ready handshake
  under Rosetta 2 on this node, while the rest of the emulated platform
  (incl. the workbench Jupyter server UI) works. This is a hard
  environmental blocker for the standard pipeline's notebook step in
  in-kind; the KFP runtime image is amd64-only (no arm64 variant of
  odh-pipeline-runtime-datascience-cpu-py312-ubi9 exists).
- Under test: heartbeat roundtrip from a fresh socket (does the kernel's
  zmq I/O loop answer at all?) and a clean wait_for_ready with explicit
  exception capture. If the kernel I/O is dead under Rosetta, the
  remaining options are: (a) switch Docker Desktop from Rosetta to
  binfmt-qemu emulation (Docker restart -> cluster loss, rebuild),
  (b) find the specific Rosetta incompatibility in ipykernel, (c) treat
  the notebook step as environment-limited and scope the in-kind
  assertion accordingly.

### Rosetta root cause + VM disk-full incident (2026-09-15 evening)
- Kernel-startup failure root cause: the x86_64 image runs under
  **Rosetta 2** (podman-machine's /mnt/rosetta host-side translator,
  binfmt entry "rosetta"; there is NO qemu-x86_64 binfmt entry in the
  VM). /proc forensics on a hung kernel: 6 kernel threads blocked
  forever in rt_mutex_schedule (robust futex) - a Rosetta 2 deadlock
  in threaded processes. Raw pyzmq roundtrips, bare python loops, and
  repeated zmq context create/term all work fine under Rosetta; only
  the ipykernel event loop deadlocks. Native aarch64 control: kernel
  ready + execute in seconds. Conclusion: ipykernel cannot work under
  Rosetta on this machine; QEMU (binfmt) emulation is the candidate
  fix (futex passthrough).
- The KFP runtime image odh-pipeline-runtime-datascience-cpu-py312-ubi9
  is amd64-only (tag 2025b-v1.36 exists, single-arch manifest; no
  arm64 variant) - x86_64 emulation is unavoidable for pipeline steps.
- The VM is **podman machine** (applehv, 4 CPU, 16GiB, 100GB disk),
  NOT Docker Desktop. docker.sock is a symlink to podman's socket.
- INCIDENT: while registering a runtime binfmt switch, discovered the
  VM disk was 100% full (100GB/100GB). Disk-full killed sshd and the
  podman service inside the VM: docker/podman CLI dead, no VM shell.
  The kind cluster survives as orphaned processes (API healthy, node
  Ready) but is fragile (no image pulls). kubezoo cluster likewise.
- Recovery plan chosen with user: podman machine stop -> set
  --disk-size 150 -> start. Kind node containers use restart=on-failure
  (last exit 137 from SIGKILL) so they should auto-restart at boot,
  recovering both clusters with state intact. If that fails, rebuild.
- After VM recovery, redo the binfmt switch cleanly (the earlier
  registration attempt left a bogus qemu-x86_64 entry whose magic is
  literal text - harmless, never matches; it also vanishes on VM
  restart). Correct registration (from VM shell, as root):
  printf ':qemu64new:M::\177ELF\002\001\001\000\000\000\000\000\000\000\000\000\002\000\056\000::/usr/bin/qemu-x86_64-static:P' > /proc/sys/fs/binfmt_misc/register
  (octal bytes for the x86_64 ELF magic; rosetta stays enabled but the
  new entry is checked first by the kernel).
- Then re-verify: docker run of the runtime image shows
  qemu-x86_64-static in ps, and the jupyter_client wait_for_ready
  test (kt2/kt3.py in /tmp/kf3x) must print KERNEL READY.

### VM recovery outcome + image cleanup (final state)
- podman machine stop -> set --disk-size 150 -> start: VM back, sshd +
  podman service healthy again.
- growpart /dev/vda 4 + xfs_growfs: root fs now 150G (was 100G).
- **BOTH CLUSTERS LOST THEIR RUNTIME STATE**: the live container
  writable layers (etcd member data, node containerd images) are gone
  from podman storage - the storage resync after the disk-full
  incident left only the 3.1MB initial-provisioning layer per kind
  node (dated Sep 12 22:37). kind-control-plane boots to systemd +
  containerd then fails "Failed to execute our own binary" (its
  writable layer is the pristine initial state). Rebuild of both
  clusters is required (kind create + full in-kind setup from the
  handoff). The kind node images (kindest/node arm64, 2 digests) were
  also deleted during cleanup - re-pull from docker.io/kindest/node.
- Image cleanup: 78 images -> 9. Disk 88G used/100G (88%, then full)
  -> 70G/150G (47%), 81G free.
- Deleted (all re-pullable from registries or superseded): all 25
  quay.io/jdanek/kubezoo:* tags (all amd64 builds, on quay), 3 x
  odh-base-image-cpu-py312-c9s pulls (multi-arch tag exists; amd64 +
  one arm64 pulls), 5 dangling <none> blobs (6.9GB arm64 local-build
  leftovers + 606MB amd64 + 937MB), notebook-rpm-lockfile 1.38GB,
  mount-test 1.21GB, ro-probe, hermeto 832MB, openshift
  origin-oauth-proxy 515MB, jdanek api-extension / oauth-server /
  origin-oauth-proxy:patched, golang 1.24 kept, kindest/node x2
  deleted by mistake in final batch (public image, re-pull).
- KEPT: odh-pipeline-runtime-datascience-cpu-py312-ubi9:2025b-v1.36
  3.16GB amd64 (both tags, same id f442feccf84a), golang:1.24/1.27,
  python:3.12-slim (amd64 pull) / 3.13-slim (arm64), buildkit,
  uv-readonly-find-links-podman, alpine:3.20, distroless/static.
- amd64-only inventory (for the record): the pipeline runtime (no
  arm64 variant exists in quay repo - single tag, single-arch
  manifest); the kubezoo operator builds (all amd64); odh-base-image
  amd64 pulls (tag is multi-arch); old origin-oauth-proxy; local
  notebook-rpm-lockfile build. python:3.12-slim + distroless are
  multi-arch images with amd64 local pulls.
- Next steps: (1) rebuild the kind cluster + in-kind platform,
  (2) FIRST register the qemu-x86_64 binfmt entry (correct octal
  magic, name e.g. qemu64new) so pipeline steps run under QEMU
  instead of Rosetta, (3) verify jupyter kernel ready-handshake in a
  test pod, (4) rerun robot 0502, (5) cypress testWorkbenchStatus,
  (6) commit both repos.

## Full rebuild procedure (verified 2026-09-16, fresh podman machine)

Rebuilds everything from scratch: podman machine + kind cluster + platform +
probe kubeconfig. Use after a machine delete or total storage loss.

1. **Machine** (user spec: 4 CPU / 16GB / 100GB / Rosetta):
       podman machine rm --force podman-machine-default
       podman machine init podman-machine-default --rootful --cpus 4 --memory 16384 --disk-size 100
       podman machine start
   - **--rootful is REQUIRED**: the default (rootless, runs podman as the core
     user) makes the docker API report SecurityOptions name=rootless, and kind
     v0.33 then refuses with "running kind with rootless provider requires
     Delegate=yes" - even though both the system and user podman units already
     have Delegate=yes set. The check is triggered by the rootless flag itself,
     not by actual cgroup delegation. Rootful also fixes it (daemon runs as
     root, no name=rootless option).
   - **Rosetta needs no flag**: /mnt/rosetta + the binfmt entry ship in the
     machine-os image (podman 6.x). Verify: podman run --rm --platform
     linux/amd64 docker.io/library/busybox:1.36 uname -m  => x86_64.
   - No --rosetta / --vm-type / --name flags exist in this podman version;
     NAME is a positional argument.
2. **Cluster** (kind v0.33.0 on the host, talks to the machine via the
   /var/run/docker.sock -> podman.sock shim):
       cd /tmp/rhoai-odh3x
       kind create cluster --config components/00-kind-cluster.yaml \
         --image docker.io/kindest/node:v1.34.11@sha256:44e222ee2132dab25ff87301682f89eb82c7880ea3a1bf543bfe9708fd08d67d
       kind export kubeconfig --name kind --kubeconfig /tmp/kf3x/kind-kubeconfig
   - API server on 127.0.0.1:6443 (the config's value). The previous cluster's
     8443 was an ad-hoc earlier choice; 8443 is now taken by another local
     service, 6443 is free. The robot derives its contexts from the KUBECONFIG
     server address, so the port change is transparent to it.
   - Gateway (dashboard) stays on host 80/443 via the config's port mappings.
3. **Platform** (~10-15 min):
       cd /tmp/rhoai-odh3x
       KUBECONFIG=/tmp/kf3x/kind-kubeconfig .venv/bin/python \
         components/deploy.py --workbench-branch=v1.36.0
   - deploy.py got a new fix for a within-batch CRD race: the components/crds
     kustomization mixes CRDs and CRs (Authentication CR in auth.yaml); a fresh
     cluster applies the CR before the apiextensions controller registers the
     kind -> "resource mapping not found". The step now re-applies the batch
     after the authentications CRD is Established (idempotent).
   - Result: 34 pods Running - DSPO, notebook-controller (+odh controller),
     rhods-dashboard 4/4, argocd 7, istio 2, kyverno 4, cert-manager 3, minio,
     oauth-server, api-extension, openshift-service-ca(+operator), DSC/DSCI.
   - Dashboard reachable through the gateway on a fresh deploy
     (https://rhods-dashboard.127.0.0.1.sslip.io/ => 401 Unauthorized for
     anonymous = correct); the istio-system policy-group=ingress label fix from
     the 2.x era was NOT needed here.
4. **Probe kubeconfig** (htpasswd cluster-admin, for the robot/cypress):
       TOKEN=$(kubectl --kubeconfig=/tmp/kf3x/kind-kubeconfig create token \
         htpasswd-cluster-admin-user -n oauth-server --duration=8760h)
       # CA: python yaml parse of kind-kubeconfig clusters[0]
       # -> /tmp/kf3x/make-probe-kc.py rewrites
       # /tmp/rhoai-odh3x/.kubeconfig-probe with context
       # default/127-0-0-1:6443/system:serviceaccount:oauth-server:htpasswd-cluster-admin-user
   - Verified: kubectl --kubeconfig=.../.kubeconfig-probe get nodes => Ready.


## Session 17 results (2026-09-16)

Bottom line: **cypress testWorkbenchStatus.cy.ts now passes end-to-end on the in-kind cluster** (run 10: 1 passing, 1m10s, project namespace self-cleaned by the test's own after-hook). The robot 0502__ide_elyra.robot (Smoke) remains blocked by the Rosetta ipykernel deadlock - triple-confirmed, only plausible fix is a macOS 27 update (user decision, not yet done). The machine was rebuilt to the user's spec this session and the whole platform re-deployed from scratch; every fix below is now persisted in deploy.py/components so a from-zero rebuild reproduces the passing cypress state.

### Machine rebuild to user spec

- Machine is now podman-machine-default, 4 CPU / 16GiB / 100GiB, **rootful + Rosetta** (user chose this spec; previous machine was rootless/smaller).
- kind refuses to start in rootless mode here (Delegate=yes refusal) - the kind cluster must run in the rootful machine; init it with --rootful or the node image import fails.
- Rosetta is bundled automatically and works (amd64 busybox in the VM runs x86_64). That is also what makes the robot blocker below possible.
- kind cluster created with the digest-pinned node image (recipe in the rebuild section at the bottom), API on 127.0.0.1:6443 (8443 was taken by another local service on this machine).

### Rosetta ipykernel deadlock - triple confirmed (robot blocker)

The KFP pipeline runtime image (quay.io/opendatahub/odh-pipeline-runtime-datascience-cpu-py312-ubi9:2025b-v1.36) is amd64-only. Under Rosetta, a fresh pod running a plain ipykernel exec deadlocks:

    t=481.4 WAIT FAILED: Kernel didn't respond in 480 seconds; kernel proc alive: True
    (all 7 kernel threads parked in rt_mutex_schedule)

Confirmed three ways: robot run 64 (the pipeline step), a dedicated kerneltest pod (kerneltest.yaml, deleted after use), and a fresh plain probe pod. The deadlock is in the Rosetta syscall translation, not in our stack - nothing in the image, kernel args, or node config changed it. Options: (a) macOS 27 update (available on the host, ~5GB, needs reboot) if it ships a Rosetta fix, (b) accept the robot failure on this machine, (c) wait for an arm64 pipeline-runtime image. Do not burn another 40-minute robot run to re-confirm.
### Browser login chain (persisted in deploy.py)

The fresh cluster could not log in through the browser because the oauth-proxy sidecar patch was a manual step. It is now a deploy.py log group ("Patch dashboard with oauth-proxy sidecar (browser login)") after "Install ODH Dashboard": it waits for the deployment, runs components/oauth-server/patch-dashboard.py, parses the "saved <path>" line, kubectl apply + rollout status. Verified end-to-end: GET / -> oauth-proxy 302 (Set-Cookie _oauth_proxy_csrf) -> mock /oauth/authorize -> form POST admin/password -> /oauth/callback?code= -> proxy redeems at http://oauth-server.127.0.0.1.sslip.io/token -> mock mints an SA TokenRequest token (168h) -> userinfo -> Set-Cookie _oauth_proxy=<b64 admin@cluster.local|...> -> 302 / -> 200.

Two mock-oauth fixes were needed:

1. components/oauth-server/oauth-server.go: the provider link list now starts with an htpasswd link (a role=link anchor named exactly "htpasswd"). cypress requires that link name (ADMIN_USER_AUTH_TYPE=htpasswd in frontend/.env.cypress). Image rebuilt with a NEW tag - components/oauth-server/oauth-server.yaml uses quay.io/jdanek/oauth-server:htpasswd-link (IfNotPresent + :latest would not re-pull). Dockerfile builder bumped to golang:1.27 (go.mod requires go >= 1.25; the old 1.24 base failed the build).
2. The mock /token handler PANICS (serviceaccounts "X" not found -> connection reset -> gateway 503 "upstream connect error or disconnect/reset before headers" -> callback 500) when the SA for the redeemed user does not exist. deploy.py's oauth user list now includes plain "admin" (previously it had adminuser/admin-user/contributor-username but not admin). Invalid codes 401 without panicking, which is why routing looked healthy while direct curl probes failed.
3. Note: the callback 403 "http: named cookie not present" seen with separate curl calls is the oauth-proxy CSRF check (cookie set on the first /oauth/authorize 302) - a browser/cypress carries the cookie jar, so it is not a real bug; verify with curl -c/-b.

### 3.x project = plain namespace; DSC must serve v2

- In 3.x a dashboard "project" is a plain k8s namespace labeled opendatahub.io/dashboard=true (created by the cypress task via oc new-project + oc label). There is no DataScienceProject CR - the 3.x backend has no dataScienceProjects route; projectListPage uses the namespaces API.
- The dashboard fetches DSC at v2 (backend/src/utils/dsc.ts: listClusterCustomObject datasciencecluster.opendatahub.io v2) and DSCI at v1. With the fake DSC CRD serving v1 only, the project detail page 503'd (repeating "Failure to fetch dsc: 404 page not found" in the dashboard log) and the page sidebar never rendered. Fix: v2 added to components/crds/dsc.yaml (served:true, storage:false, preserve-unknown-fields) - applied live, dsc fetch errors -> 0.

### Spawner Create button: missing HardwareProfile (two-part)

The workbench spawner's submit button (data-testid submit-button, id create-button) stays disabled when the hardware-profile form data is empty:

- SpawnerFooter: isButtonDisabled = createInProgress or !checkRequiredFieldsForNotebookStart(...) or !isHardwareProfileValid or (!isProjectScopedAvailable and image IS ns == project ns).
- useHardwareProfileConfig picks the first ENABLED profile for new workbenches and copies its identifiers (identifier -> defaultCount) into the form resources. With zero profiles in the cluster, formData.resources is never set, and isHardwareProfileConfigValid returns false for useExistingSettings:false with undefined resources - button disabled forever. On real 3.x clusters the ODH operator ships a default profile; the in-kind probe has no operator.
- Fix: new fake CRD hardwareprofiles.infrastructure.opendatahub.io (components/crds/hardwareprofile.yaml, added to the crds kustomization) + components/12-hardware-profile.yaml (profile "default" in redhat-ods-applications: cpu min 1/max 16/default 1, memory min 1Gi/max 32Gi/default 1Gi), applied by a new deploy.py group "Set default HardwareProfile".
- TRAP: every CPU count must be an INTEGER. validateProfileWarning -> checkDecimal warns "Minimum count for CPU cannot be a decimal" for minCount 0.25, isHardwareProfileValid then filters the profile out, and the button stays disabled with no visible error. Memory values like 1Gi parse to integer 1 and are fine. The first version of the profile used 0.25 and still failed - that was the whole cause of one extra cypress run.

### Cypress run history (this machine, this spec)

Runs 2-7 (pre-fix): config crash, /dev/tty (no pty - wrap the runner in script -q /dev/null bash run-cy.sh ...), missing htpasswd link, admin SA panic 503, DSC v2 404 (project page), disabled main Create button (no HardwareProfile CRD).
Run 8: profile existed but had decimal CPU -> still disabled.
Run 9: button enabled, workbench created, failed at "expect Running" 120s - status still Starting (the 3.22GB code-server image was being pulled from quay.io).
Run 10: PASS (1 passing, 1m10s).

### Image pull notes (in-kind)

- The spawner selects code-server-notebook (the cypress helper's preferred imagestream) and version 2025.2 = quay.io/opendatahub/odh-workbench-codeserver-datascience-cpu-py312-ubi9:2025b-v1.36 (~3.22GB). On this network a cold pull by the pod takes ~1-3 minutes.
- testWorkbenchStatus asserts the event log contains the literal "Successfully pulled image" (workbenchStatusModal.findLogEntry -> [data-testid='event-logs'] li span contains ...). A pod that finds the image already in the node's containerd logs "already present on machine" instead and FAILS that assertion. So for a clean run, evict the image from the kind node first:

      podman exec kind-control-plane crictl rmi quay.io/opendatahub/odh-workbench-codeserver-datascience-cpu-py312-ubi9:2025b-v1.36

  (the kind node is a podman container inside the machine - not visible from host docker).
- Local-only cypress change: packages/cypress/cypress/tests/e2e/dataScienceProjects/workbenches/testWorkbenchStatus.cy.ts Running-wait timeout 120000 -> 600000 (in-kind cold pulls are slower than the upstream 2-minute budget). Do not commit to upstream.
- The test's after-hook deletes the test project namespace; verified self-cleaned (0 dsp-wb-* namespaces after run 10).

### Reproduction (short form)

      # from a machine with the rebuilt cluster + deploy.py run complete:
      podman exec kind-control-plane crictl rmi quay.io/opendatahub/odh-workbench-codeserver-datascience-cpu-py312-ubi9:2025b-v1.36 || true
      script -q /dev/null bash /tmp/kf3x/run-cy.sh testWorkbenchStatus.cy.ts

    (run-cy.sh: USERNAME/PASSWORD admin/password, frontend .env.cypress ADMIN_USER_AUTH_TYPE=htpasswd, KUBECONFIG probe for cy.exec oc calls)

### Uncommitted changes this session

- rhoai-odh3x: components/deploy.py (CRD race re-apply fix; oauth-proxy sidecar step; "admin" in oauth user list; "Set default HardwareProfile" group), components/crds/dsc.yaml (+v2), components/crds/hardwareprofile.yaml (new), components/crds/kustomization.yaml (+hardwareprofile), components/12-hardware-profile.yaml (new), components/oauth-server/{oauth-server.go (htpasswd link), Dockerfile (golang 1.27), oauth-server.yaml (:htpasswd-link)}, docs/odh-3x-handoff.md (this session).
- ods-ci-3x: tests/Tests/0500__ide/0502__ide_elyra.robot + 4 resources (from the earlier span; still uncommitted).
- odh-dashboard-3x (local only, do not commit): packages/cypress/cypress/utils/discoverTestPatterns.ts try/catch -> [], testWorkbenchStatus.cy.ts timeout 120000 -> 600000.

### Open

- Robot 0502 Smoke: blocked on Rosetta ipykernel deadlock. macOS 27 update is the only known fix path (user decision).
- Whether other workbench/notebook cypress specs (auth sidecar, resource customization, stop/start, delete) also pass on this cluster - testWorkbenchStatus is the one requested; the rest were proven on the old (pre-rebuild) cluster.
