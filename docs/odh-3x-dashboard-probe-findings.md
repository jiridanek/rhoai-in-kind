# ODH 3.x Dashboard Probe — Findings

**Method** — autonomous spike, fully isolated (a `git worktree` at `main` + a disposable `kind` cluster; the working tree was untouched):
- Retargeted **only the dashboard** to 3.3 (`v3.3.1-odh`) in the worktree — a 3-line change in `components/04-odh-dashboard.yaml` (app `targetRevision` + 2 image refs). The **entire 2.x base stayed unchanged** (kind/ArgoCD/Kyverno/Istio/cert-manager/api-extension/oauth/MinIO, DSPO, notebooks, fake DSC/DSCI).
- Fresh `kind` cluster (v1.34.11), api-extension image `kind load`-ed, `deploy.py` run via **`uv run`** (the project requires **Python 3.14**; `t"…"` template-strings in `rhoai_in_kind/__init__.py` don't parse under the machine's default 3.12 — a red herring, not a code bug).

## Result: the 3.x dashboard deploys, but one container crashloops

The 3.x dashboard is a monorepo image with **5 containers**. Against the 2.x base:

| Container | State |
|---|---|
| dashboard UI + Go BFFs + oauth/kube-rbac-proxy (4) | **Ready** |
| **`maas-ui`** (`quay.io/opendatahub/mod-arch-maas:v3.3.1-odh`) | **`CrashLoopBackOff`** (4 restarts) |

So **4/5 containers come up**; the pod is not fully Ready.

**Full-cluster coexistence:** 33/34 pods Running/Ready — the entire 2.x base is healthy (api-extension, ArgoCD, cert-manager, Istio, Kyverno, MinIO, oauth-server, service-CA) **plus** DSPO (`data-science-pipelines-operator`) and both notebook controllers, and the 3.x dashboard's four non-maas containers. `maas-ui` is the **sole** exception — confirming it is the only 3.x-specific delta on this base.

## Root cause of the crash

```
level=ERROR msg="automatic discovery of cluster domain failed: the server could not find the requested resource"
```

`maas-ui` (new in 3.x — the Model-as-a-Service UI) **auto-discovers the cluster's ingress domain** (to build MaaS URLs) from an OpenShift ingress resource. This kind/vanilla environment has **no `ingresscontroller` API** (and no domain configmap/env), so the discovery call 404s and the container exits.

## Consequence

- The `rhods-dashboard` deployment never reaches fully-Ready (4/5).
- `deploy.py`'s **deferred** `kubectl wait --for=condition=Available deployment -l app=rhods-dashboard --timeout=120s` therefore **times out** → `deploy.py` exits **1**. The failure is the *dashboard availability wait*, not a deploy error — everything else (infra + DSPO + notebooks + fake control plane) deployed cleanly.
- The 3.x dashboard image pulls **several** BFF images; on a cold single-node cluster that outpaced the 120s budget. CI prepulls digests to avoid this; locally, prepull or raise the wait.

## What this means for "arranging" 3.x

1. **Retargeting the dashboard is trivial** (image ref + 2 params) — confirmed working (image pulls, 4/5 containers run).
2. **3.x introduced a new container (`maas-ui`) with a new requirement: a discoverable cluster ingress domain.** The in-kind fake control plane must provide this for 3.x. This is a **bounded, 3.x-gated change to the fake control plane** (add the ingress-domain resource, or set the domain as config) — *not* a fundamental 3.x incompatibility. This is the headline "what testing 3.x entails" answer.
3. The dashboard availability **wait timeout** is too tight for cold local pulls (CI prepulls; locally prepull/raise it).

## Recommended next step (to get 3.x fully green)

Identify the **exact** resource `maas-ui` queries for the domain (its upstream source; the 404 is generic), then add a fake one to `components/07-dsc-dsci.yaml` (or a new 3.x-gated component) — the same "fake the control plane" pattern already used for DSC/DSCI.


## maas-ui container breakdown + domain-source investigation

The 3.x dashboard is a **5-container** monorepo pod (app=rhods-dashboard):

| Container | Image | State on 2.x base |
|---|---|---|
| rhods-dashboard | odh-dashboard:v3.3.1-odh (main, :8080) | running (readiness-pending) |
| kube-rbac-proxy | odh-kube-auth-proxy@sha256:dcb09f… (:8443/:8444) | **Ready** |
| model-registry-ui | odh-mod-arch-modular-architecture:v3.3.1-odh (:8043) | running |
| gen-ai-ui | odh-mod-arch-gen-ai:v3.3.1-odh (:8143) | running |
| maas-ui | mod-arch-maas:v3.3.1-odh (:8243) | **CrashLoopBackOff** (exit 1) |

maas-ui is the **only** failing container. Its args carry no domain flag (--auth-method=user_token --port=8243 …); env is only TIERS_CONFIGMAP_NS + SSL_CERT_FILE — so the domain is pure **API auto-discovery**.

**RBAC** (kubectl auth can-i --list --as=system:serviceaccount:redhat-ods-applications:rhods-dashboard) — domain discovery may read: consoles.operator.openshift.io, clusterversions.config.openshift.io, routes.route.openshift.io, ingresses, clusterserviceversions, subscriptions.

**Fakes I added to the live (disposable) cluster to test the 404:** ingresscontrollers.config.openshift.io (not even in the RBAC -> ruled out), clusterversions.config.openshift.io (version/rhoai-in-kind), consoles.operator.openshift.io (cluster, with consoleURL), and a route named rhods-dashboard (host rhods-dashboard.apps-rhoai-in-kind.test, port 8243). **None fixed it** — the error is byte-for-byte identical, so the 404 is on a **RBAC-allowed route or ingress with a specific name** that the 2.x istio-based base does not create. The frontend source lives in opendatahub-io/mod-arch-library (TypeScript); the Go server that performs this discovery is a separate repo (GitHub code search is auth-gated here), so pinning the exact resource name is a product detail the RHOAI team has immediately. This does not change the conclusion below.

**Refinement (full RBAC):** with the *unfiltered* `auth can-i --list`, maas-ui also has read on a stack of **3.x-specific MaaS/MLOps CRDs** that the 2.x base does not install: `modelregistries.modelregistry.opendatahub.io`, `llamastackdistributions.llamastack.io`, `inferenceservices.serving.kserve.io` (KServe), `featurestores.feast.dev`, `guardrailsorchestrators.trustyai.opendatahub.io`, `rhmis.integreatly.org`, `auths.services.platform.opendatahub.io`. A GET against an absent resource type returns exactly *"the server could not find the requested resource"* — the persistent 404. So maas-ui's cluster-domain discovery probes a **3.x-only MaaS/MLOps API** missing from the 2.x base. Fakes ruled out along the way: ingresscontroller (not RBAC-allowed), clusterversion, console, and named routes (rhods-dashboard/maas-ui/odh-dashboard/maas). The exact probed resource is a product detail, but the entailment is now concrete: the 3.x fake control plane must carry the MaaS/MLOps CRD substrate (model-registry, KServe, Llama Stack, Feast, TrustyAI, ...) that maas-ui discovers against.

**Interim conclusion (unchanged):** the 3.x dashboard retarget works; 3.x's new maas-ui container needs a discoverable cluster domain the in-kind fake control plane does not currently provide -> a bounded, 3.x-gated fake-control-plane change. The fakes (ingresscontroller/clusterversion/console) remain only in the throwaway cluster; they do not touch the working tree.

## Probe status (committed on odh-3x-probe) + the precise maas-ui ask

**Committed** (branch odh-3x-probe, from main 73d130e):
- 0a3ac31 — the 3-line dashboard retarget to v3.3.1-odh (components/04-odh-dashboard.yaml).
- 43398b0 — the 2.x/3.x organization docs + releases/2.25.z.yaml + releases/3.x.yaml.

**maas-ui definitive env** (from the rendered pod): image mod-arch-maas:v3.3.1-odh; env = TIERS_CONFIGMAP_NS (via fieldRef metadata.namespace -> redhat-ods-applications) + SSL_CERT_FILE; args = CA-bundle paths only (--bundle-paths, --key-file) — **no domain flag**. So the domain is pure **API auto-discovery** against a resource in redhat-ods-applications (a tiers configmap, per the env). The 2.x base has **no tiers configmap** there and none of the 3.x MaaS/MLOps CRDs, so the discovery 404s and the container exits.

**The one remaining detail (a RHOAI product detail):** the *exact* resource + field the mod-arch-maas BFF reads for the cluster domain. The mod-arch-maas source is a separate repo (GitHub code-search is auth-gated here) and is not in the local odh-dashboard checkout. Ruled out empirically: ingresscontroller (not even RBAC-allowed), clusterversion, console, and named routes (rhods-dashboard / maas-ui / odh-dashboard / maas). **Ask:** name the resource (or confirm maas-ui is optional/skippable in a non-MaaS 3.x config) -> I add the matching 3.x-gated fake to the control plane and verify 5/5.

## Rollback (fully reversible)

```
kubectl config use-context default     # restore your context (was the remote OCP cluster)
kind delete cluster kind
git -C /Users/jdanek/IdeaProjects/rhoai-in-kind worktree remove --force /tmp/rhoai-odh3x
git -C /Users/jdanek/IdeaProjects/rhoai-in-kind branch -D odh-3x-probe
```