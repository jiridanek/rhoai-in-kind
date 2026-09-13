# Testing ODH/RHOAI 2.x **and** 3.x in rhoai-in-kind — evaluation & organization

Status: **proposal** (read + decide before implementing). Everything below is grounded in
the current repo state and in RHOAI's Jira/Slack/Confluence; file/line refs are current as of
this writing.

## TL;DR / recommendation

**Do not fork the repo into a 2.x branch + 3.x branch, and do not copy subtrees per version.**
Instead, keep **one codebase (one `main`) and make the *version* a first-class, parameterized
"release profile."** A tiny `releases/<name>.yaml` becomes the single source of truth for every
version-specific pin; `deploy.py` and the three test workflows read it; "which ODH version am I
testing" becomes a one-field selection plus a CI matrix axis (`release: [2.25.z, 3.x]`).

> **The four steelman advocates (one per option, in [`docs/advocacy/`](advocacy/)) independently converge** on this steady state. The full side-by-side and the recommended **sequence** — spike 3.x on a throwaway branch to de-risk the org-independent 3.x retarget, then converge on the profile and delete the branch — is in **[`docs/odh-2x-vs-3x-verdict.md`](odh-2x-vs-3x-verdict.md).**
>
> A **second, orthogonal axis** — *how the 3.x components are deployed in kind* (apply the standalone manifests directly, as today, vs. run the 3.x **module operator**; i.e. "should it use rhods-operator?") — is answered in **§8**. It is independent of the org choice above.

Why: the thing that actually differs between 2.x and 3.x is a **small set of data** (component
refs/tags, image overrides, the test-suite refs, a few patches) — **not** the deploy logic and
**not** the shared infra (kind, ArgoCD, Kyverno, Istio, oauth fakes, MinIO). Branches/subtrees
fork the logic and infra too, which is exactly the maintenance and divergence you're trying to
avoid. The repo is already ~80% structured for the profile approach (env-driven
`WORKBENCH_BRANCH`, `workflow_dispatch` `test_repo`/`test_ref` inputs, kustomize `patches`).
This recommendation just completes that pattern.

> **Executed (evidence):** the P1 spike was run on a throwaway branch + a disposable kind cluster (see [`3x-spike-runbook.md`](3x-spike-runbook.md) / [`odh-3x-dashboard-probe-findings.md`](odh-3x-dashboard-probe-findings.md)). Result: the 2.x base and the **3.x dashboard** coexist cleanly — **33/34 pods Ready**. The *only* 3.x delta found is that the new `maas-ui` BFF (mod-arch-maas) requires a **MaaS/MLOps CRD substrate** the 2.x base does not install. This validates Option C — one shared infra tree, a small *enumerable* 3.x delta — and confirms the 3.x dashboard *deploy* is low-cost (same `onprem/` unit + 2 new params).

---

## 1. What "test 2.x and 3.x" concretely means

From the RHOAI release process (Confluence "RHOAI Z-stream Release Process") and the release
working-group channels:

- **"2.x" today = the `2.25.z` Z-stream** (the stable EUS 2.x line). This repo already targets
  exactly this train (README pins it to "rhoai-2.25", notebooks `v1.36.0`).
- **"3.x" = the 3.y y-stream feature line** (3.0, 3.1, …) **plus the `3.3.z` Z-stream** (the
  current stable EUS 3.x line), plus upcoming 3.4 / 3.5 / 3.6 (a dedicated
  `#wg-3_N-openshift-ai-release` channel per minor).
- **Components are developed upstream** (`opendatahub-io/*`) and the release flow **cherry-picks
  approved fixes into downstream z-stream branches** in `red-hat-data-services/*`. Fixes must land
  in `opendatahub/main` first, then are cherry-picked downstream.
- **Strategic shift** (Slack "#wg-rhoai-odh-test-release-strategy", thread "A Product-centric
  Development Workflow for RHOAI"): RHOAI is **collapsing the ODH midstream build** to focus on
  **product-level integration from upstream** + upstream contributions, carrying over the "Bodies
  of Water" (RHOAIENG-24681) work — **early-gate / PR promotion gating + e2e coverage across
  component teams**.

**Implication for this repo:** "test a version" = *deploy the upstream component repos at that
release train's branches/tags, then run the matching test suites.* That is precisely what
`deploy.py` already does — it pulls from `opendatahub-io/notebooks`,
`opendatahub-io/data-science-pipelines-operator`, `opendatahub-io/odh-dashboard`, and
`opendatahub-io/kubeflow` at pinned refs. Extending to 3.x means pointing those same repos at 3.x
refs and adjusting the downstream of it. It does **not** require a different deployment *strategy*
or a different *kind* approach.

## 2. The version surface (every place 2.x is pinned)

The complete list of version-specific pins. If you can see every version knob in one place, the org
decision becomes easy.

**ODH-component pins (the things that fork between 2.x and 3.x):**

| Component / concern | Where it's pinned | Current 2.x value |
|---|---|---|
| Workbench images (notebooks repo checkout ref) | `deploy.py:506-508` (`workbench_repo` + `--workbench-branch`); workflows | notebooks tag **v1.36.0** |
| Workbench image registry tag | `...-with-ods-ci.yaml:41` (`NOTEBOOK_IMAGE_TAG`) + matrix `prepull_images` digests lines 64-179 | **2025b-v1.36** (+ per-image digests) |
| DSPO (kf-pipelines) ref + image overrides | `03-kf-pipelines.yaml:35` (`targetRevision`) + env overrides 66-71 | **v2.15.1**; `proxyv2-ubi8:2.5.0`, `jdanek/origin-oauth-proxy`, `mariadb-103` |
| ODH Dashboard ref + image + oauth-proxy overrides | `04-odh-dashboard.yaml:39,65,103-106` | **v2.37.1-odh** (+ dashboard image + 2 oauth-proxy digests) |
| Notebook controllers (kubeflow ref) | `09-kf-notebooks/kustomization.yaml:34-35` | **v1.10.0-5** |
| Fake DSC/DSCI + per-component `Dashboard` CR | `07-dsc-dsci.yaml:11,15,52,201` (2.13.0); 203-216 (`components.platform.opendatahub.io/v1alpha1 Dashboard`, 2.22.0); mgmtStates 66-97 | DSC **2.13.0** / component CR **2.22.0**; mgmtState set for codeflare/kserve/trustyai/ray/kueue/workbenches/dashboard/modelmeshserving/datasciencepipelines/trainingoperator/modelregistry |
| Fake CRDs | `components/crds/` (11 CRDs incl. `components.platform.opendatahub.io_dashboards`) | 2.x-shaped |
| Kyverno policies + kustomize patches | `components/02-kyverno/` (imagestream-status, dspa-pipelinestore, route generation, CA injection) | 2.x-shaped |
| **Test suite** refs | ods-ci `release-2.25` (…-with-ods-ci.yaml:198); odh-dashboard cypress `v2.37.1-odh` (…-with-cypress.yaml:15,59); opendatahub-tests SHA `94670b33…` (…-with-odh-tests-shiftleft.yaml:15) | 2.x test branches |
| Test config | `components/ods-ci/test-variables.yml`, root `test-variables.yml` | 2.x keys |

**Shared infra (version-independent of ODH — must NOT be forked per version):**

kind node **v1.34.11** (`components/00-kind-cluster.yaml` + pre-pull steps), ArgoCD **v3.5.1**
(`deploy.py:188`, `01-argocd`), Kyverno **1.19.0** (`02-kyverno/kustomization.yaml:8`),
Istio **1.26.2** (`deploy.py:207`), cert-manager **v1.18.2** (`deploy.py:178`), Gateway API
v1.3.0, `api-extension`, `oauth-server`, MinIO, coreDNS, and all the deploy *orchestration
logic* in `deploy.py` + the test-runner steps in the workflows.

> Note how small the fork-prone set is: ~9 data fields + 2 test-config files. That's the whole
> argument for a profile.

## 3. What 3.x actually changes (the delta)

Grounded in the Confluence "ODH Dashboard: Builds & Konflux Guide" and in-repo comments:

1. **Dashboard — the *source* is a monorepo, but the *deploy* is unchanged (verified).** The 3.x
   dashboard is built from an **npm-workspaces monorepo** with a **modular-architecture** (federated
   UI modules under `packages/<module>/`, Go BFFs, `BUILD_MODE=ODH`/`RHOAI`, hermetic downstream
   builds). **However**, the *deploy* unit is the same as 2.x: `v3.3.1-odh` ships the identical
   `manifests/rhoai/onprem/` layout (`apps/`, `kustomization.yaml`, `params.env`, `params.yaml`), so
   retargeting the deploy is **low-cost** — override the image tag + set the two **new** `params.env`
   vars (`kube-rbac-proxy` = odh-kube-auth-proxy, `gateway-name`). The monorepo shows up as (a) the
   *image* is built from the monorepo, and (b) the **cypress test-runner** needs the workspaces layout
   (`main` "broke the install" per the cypress workflow) — that's where the real 3.x dashboard effort
   lands, not in the deploy.
2. **New/changed API** — the per-component CR (`components.platform.opendatahub.io`) and
   "bring-your-own-id-connect" (comment in `04-odh-dashboard.yaml:37` notes `v2.37.1-odh` "seems
   the last without bring-your-own-id-connect"). 3.x may need new fake CRDs / different oauth. **Spike-confirmed (concrete):** the new 3.x `maas-ui` BFF requires a MaaS/MLOps CRD substrate — `modelregistries.modelregistry.opendatahub.io`, `inferenceservices.serving.kserve.io` (KServe), `llamastackdistributions.llamastack.io`, `featurestores.feast.dev`, `guardrailsorchestrators.trustyai.opendatahub.io`, `rhmis.integreatly.org`, `auths.services.platform.opendatahub.io` — none installed by the 2.x base; `maas-ui` crashloops until that substrate (or a non-MaaS 3.x config) is present.
3. **"AI Pipeline" rename** (Elyra runtime `display_name` "Data Science Pipeline" → "AI Pipeline")
   — a **3.0** change (RHOAIENG-32633; in-repo comment `09-kf-notebooks/kustomization.yaml:26-33`).
4. **Workbench images** — new names/tags (the py312 set is already the 2.25 train; 3.x may shift
   again) → new `NOTEBOOK_IMAGE_TAG` + prepull digests.
5. **DSC component set / `managementState`** — trainingoperator, modelregistry, kserve,
   model-mesh, etc. may differ.
6. **Test suites** — 3.x branches; expect UI/API-driven failures to triage; `test-variables` may
   gain 3.x keys.

Everything else (kind, ArgoCD, Kyverno, Istio, cert-manager, oauth fakes, MinIO) is **unchanged**
and stays shared.

## 4. Organization options

> Steelman briefs per option — each written by a dedicated advocate arguing its own case against the *real* repo (version surface, deploy flow, workflows) — are in [`docs/advocacy/`](advocacy/): A-separate-branches · B-subtrees · C-release-profile · D-hybrid.

### A. Separate branches (`main` = 2.x, `odh-3.x` branch — or `odh-2.x` + `odh-3.x`)
- **Pro:** each branch is a self-consistent, known-good config; minimal risk to the working 2.x;
  trivial to start (`git branch`, edit pins).
- **Con:** every shared-infra fix must be **cherry-picked/merged into both** (divergence); CI
  **doubles** in maintenance *and* history splits; you **cannot A/B compare** what differs between
  versions (the whole point of testing both); a 3rd/4th version (3.4, 2.25.12) means more branches.
  The "what changed between 2.x and 3.x" answer is buried across two divergent trees.

### B. Subtrees in main (`variants/2.x/` + `variants/3.x/`, or `components-v2/` + `components-v3/`)
- **Pro:** single branch, single history, both testable from one CI; shared infra can live once.
- **Con:** you duplicate *most* of `components/` (the fork-prone set is spread across
  `deploy.py` + 3 Argo/kustomize files + 3 workflows, not one dir), so subtrees drift in ways
  that are **hard to see**; `deploy.py` and the workflows must become variant-aware anyway; bigger
  diffs; the shared infra you wanted to keep once is either duplicated or awkwardly cross-referenced.

### C. **Single codebase + parameterized "release profile"** ← **recommended**
- One `deploy.py`, one infra set, one set of test-runner steps. The **only** version-specific
  thing is a `releases/<name>.yaml` (the ~9 data fields + test-suite refs from §2). `deploy.py`
  takes `--release <name>`; the workflows take a `release` input and a `release` **matrix axis**.
- **Pro:** logic + infra shared (no fork, no cherry-pick burden); "which version" is a 1-field
  change; the **2.x↔3.x diff is literally the diff between two ~40-line profile files** — visible,
  reviewable, exactly what you want; scales to N release trains (add a file, don't merge a branch);
  CI cost is opt-in (run 3.x on schedule/manual, not on every PR).
- **Con:** a **one-time refactor** to make `deploy.py` + the 3 workflows *consume* the profile
  (and to inject refs into the Argo/kustomize files). Real but bounded work that de-risks the repo.

### D. (sub-technique of C) per-release **kustomize overlays** for the Argo refs
Keep `03-kf-pipelines.yaml` / `04-odh-dashboard.yaml` as kustomize **bases** and add
`releases/<name>/` **overlays** that set `targetRevision`/`images`/`patches`. More
kustomize-native, keeps patches declarative, and `kustomize build releases/3.x/04` is exactly what
deploy applies. Cleanest way to keep per-version pins where they already live (in kustomize).

**Verdict:** **C** (with **D** as the mechanism for the Argo refs). A and B fork logic/infra that
shouldn't fork; C isolates the actual variable.

## 5. Target design (concrete)

Layout (the profile files are added in this round):

    releases/
      README.md            # profile schema + how to add a release
      2.25.z.yaml          # extracted current 2.x pins (default)
      3.x.yaml             # 3.x pins (draft, with TODOs)

A profile (`releases/<name>.yaml`) declares:
- **component refs:** `workbench_branch`, `notebook_image_tag`, `dspo_target_revision`,
  `dashboard_target_revision` (+ dashboard image + oauth-proxy image overrides),
  `notebook_controller_ref`, plus the DSPO env image overrides.
- **fake control-plane:** `fake_dsc_version`, `component_cr_version`, the DSC
  `managementState` set, and which fake CRDs to apply.
- **deploy mode (3.x):** per-component `deploy_mode: manifests | operator` (default `manifests`; see §8) — apply the component's standalone manifests directly, or drive it with its 3.x module operator.
- **tests:** `ods_ci_ref`, `cypress_dashboard_ref`, `opendatahub_tests_ref`,
  `test_variables_file`, and the per-image `prepull` digests.

Consumption:
- **deploy.py:** `--release 2.25.z` (env `RELEASE`, default `2.25.z`). Load profile → set
  `workbench_branch` + build/apply the Argo app refs (via D's overlays or a small template) → run
  the **identical** flow as today.
- **Workflows:** add a `release` input (default `2.25.z`) and an optional `release` matrix axis
  `[2.25.z, 3.x]`. Thread it into `deploy-stuff` (workbench-branch), the three test-suite
  checkout refs, and the test-variables selection.
- **2.x stays the default** → existing green CI is behaviorally unchanged. **3.x starts as manual /
  `workflow_dispatch`**, promoted to schedule once green.
- **Sync guard:** a tiny linter/test asserting the profile's cross-referenced pins are internally
  consistent (workbench_branch ↔ notebook_image_tag ↔ prepull digests ↔ DSPO digests) — this
  *automates* the many "CAUTION: keep in sync" comments currently in the workflows.

## 6. What it would entail (phased plan)

| Phase | Work | Effort | Gate / risk |
|---|---|---|---|
| **P0 — extract 2.x into a profile** (refactor, zero behavior change) | Extract §2 pins → `releases/2.25.z.yaml`; make `deploy.py` + 3 workflows read it. | ~0.5–1 d | **All 3 workflows still green on main** (regression gate). Low risk, pure plumbing. |
| **P1 — 3.x deploy spike** | Author `releases/3.x.yaml`; get `deploy.py --release 3.x` to bring up a 3.x stack in kind. **Hardest: the dashboard monorepo** — but the cypress workflow *already* checks out the full npm-workspaces monorepo and `npm ci`s at the root, so it's partly pre-plumbed (just swap `test_ref` + the deployed dashboard image pin). Plus any new CRDs / bring-your-own-id-connect, **and the deploy-mode choice (standalone manifests vs 3.x module operator, §8)**. | ~1–3 d | Manual-only. Where most of the real work lives — and it's **independent of the org choice** (A/B hit it too). |
| **P2 — 3.x test suites** | Point ods-ci / odh-dashboard-cypress / opendatahub-tests at 3.x refs; update test-variables; triage (expect UI/API-driven failures). | ~1–2 d each | Some tests won't exist/apply in 3.x and vice-versa — expect a curation pass. |
| **P3 — CI matrix + guard** | Add the `release` matrix axis; 3.x on schedule/manual; add the sync linter; update docs. | ~0.5 d | CI cost ≈ +1× for a full 3.x matrix. |
| **Ongoing** | Bump profiles per release train (2.25.z → 2.25.N, 3.x → 3.4/3.5/…). | trivial | A new ~40-line file per version, no branch merges. |

**Net:** the org work (P0 + P3) is modest; the **dominant cost is P1 (the 3.x dashboard/CRD
retarget), which you'd pay under *any* option.** Choosing C doesn't add cost — it removes the
ongoing divergence cost that A/B would add on top.

## 7. Decision points / open questions

1. **Which 3.x target?** RHOAI 3.x ↔ ODH 3.x is **1:1** (RHOAI 3.3 = ODH 3.3, per the Feast/ODH/RHOAI
   version matrix), so "pick a 3.x" = "pick an ODH 3.N". Recommend the **3.3 EUS Z-stream** to mirror
   how 2.x is pinned to the stable `2.25.z`. Concrete candidates (from the upstream repos, Sep 2025):
   - **Dashboard:** clean per-version tags — **`v3.3.1-odh`** (3.3 EUS, mirrors the current `v2.37.1-odh`);
     newer y-streams `v3.4.4-odh`, `v3.5.0-odh`, `v3.6.0-ea1-odh`.
   - **Notebooks:** a release-TRAIN branch + `v1.x.y` tag + `<train>-v1.N` image tag (2.x = `2025b` /
     `v1.36.0` / `2025b-v1.36`); the 3.x train is a newer one — confirm from the release mapping.
   - **DSPO:** **no `stable-3.x` branch exists** (only `main` / `stable` / `stable-2.x`) → 3.x = `main` or `stable`.
   - **Kubeflow notebook controllers:** `v1.10.0-N`, 3.x in the `v1.10.0-6`..`15` range.
   Confirm exact per-component refs against the release tracker / a fresh cluster (see
   `releases/3.x.yaml`). You can have both a `3.3.z` and a `3.x-main` profile.
2. **Upstream vs downstream?** This repo uses **upstream** (`opendatahub-io/*`,
   `quay.io/opendatahub/*`, non-hermetic). **Downstream** (`red-hat-data-services/*`) = hermetic
   builds, `registry.redhat.io`, z-stream branches, `BUILD_MODE=RHOAI`, needs registry access.
   Recommend **start upstream** (matches the repo, no new creds); add a downstream variant later
   only if product-branding / registry behavior matters for the tests you run.
3. **CI cost.** A full 3.x matrix ≈ **2× runner time**. Mitigate: 3.x **manual/schedule-only** at
   first, and/or a **3.x smoke subset** (a few robot cases + a couple cypress suites) rather than
   the full matrix.
4. **Structural divergence risk.** If 3.x needs *different deploy logic* (not just different pins),
   model it as a `variant` / hooks field **inside** the one `deploy.py` — do **not** fork the
   repo for it. The only case that would push toward option A, and even then only for the step.
5. **The product-centric shift.** "Version" is moving toward product-level integration from
   upstream; the kind approach (deploying upstream components at pinned refs) **aligns** with that,
   so C stays valid. Keep profile names as **release-train names** (2.25.z, 3.3.z, …) so they
   survive whatever the upstream/downstream naming settles into.

## 8. Operator model for 3.x: does rhoai-in-kind need the (module / platform) operator?

This is a **second, orthogonal axis** to the org choice in §4 (branch / subtree / profile), and it's
the one behind "the repo doesn't use rhods-operator — maybe it should?". It's a *deployment-mode*
question: **how do the 3.x components get deployed in kind** — applied directly (what the repo does
today) or driven by the 3.x operators? It applies under *any* org option and is part of the P1 spike.

**What the repo does today (2.x).** The README is blunt: *"The conspicuously missing component is of
course the ODH Platform Operator."* The repo skips the platform operator and instead (a) deploys the
components **directly** (ArgoCD/kustomize at pinned refs — `03`/`04`/`09`), and (b) **fakes the
control plane**: fake DSC + DSCI (`components/crds/dsc.yaml`, `dsci.yaml`), a fake per-component
**`dashboards.components.platform.opendatahub.io`** CRD (copied straight from the
`opendatahub-operator` bundle) + a fake `Dashboard` component CR with `status.url` set
(`components/07-dsc-dsci.yaml:203-216`), and a fake CSV. So the repo *already* models the CR-driven
desired state — it just replaces "the operator reconciles the CR → workload" with "apply the workload
directly."

**What 3.x changes (modular → "singular deployments").** 3.x's modular architecture "evolved into
**singular deployments**": each component is a self-contained **module** with its own **module
operator** that can deploy it **standalone** (e.g. "Dashboard Module Operator and Standalone
Deployments … merged in 3.5"), driven by its **component CR** (`dashboards.components.platform.
opendatahub.io`). The platform operator now *integrates* the modules rather than owning their
deployment. Decisively, the **official RHOAI/ODH dashboard e2e flow already runs with
`DEPLOY_RHODS_OPERATOR=False`** ("Path C") — i.e. testing a component *without* the platform operator
is an officially-supported mode, which is exactly this repo's posture in kind.

**Why this helps the repo, not hurts it.** The repo's core design — skip the platform operator, deploy
the components you care about — maps *directly* onto the 3.x **standalone deployment**. In 2.x that was
a workaround for the heavy platform operator; in 3.x it's a **designed, supported path**. The 3.x
components ship a standalone deployment; the kind env just applies it.

**Should it run the platform (rhods) operator in kind? No.**
1. It's an OpenShift-native OLM operator (CSV/Catalog/SCC/routes/image-registry) — running it in vanilla
   kind is precisely the obstacle class this repo exists to work around; large + fragile.
2. The tests exercise **deployed workload behavior** (dashboard UI, workbench spawn, pipelines), not
   platform-operator reconciliation — the operator is a "how it's deployed" detail the tests don't observe.
3. 3.x is moving *away* from "one platform operator does everything," so betting the env on it goes
   against the grain.
4. The repo already fakes the DSC/DSCI + component-CR layer — the minimal stand-in for "the operator
   decided to deploy these."

**Should it run the per-component 3.x MODULE operator? Only where fidelity needs it.** The module
operator is single-component and reconciles the component CR → workload. Running it in kind would
(a) raise fidelity — you test the exact workload/config the operator emits, not hand-applied manifests
that must manually track it; (b) let you exercise the new 3.x "module operator + component CR"
reconciliation path. But it's more work (its CRDs, RBAC, possibly webhooks; it may still be
OpenShift-flavored — **feasibility in vanilla kind is unproven → spike it**), and it's only worth it if
direct-deploy isn't already faithful.

**Recommendation (the operator axis).**
- **Default: keep "deploy the component directly + fake the CR/DSC layer"** — least work, matches 2.x,
  matches the official `DEPLOY_RHODS_OPERATOR=False` mode. Independent of the org choice.
- **Make the directly-applied manifests the 3.x *standalone-deployment* manifests** (the module's
  shipped standalone kustomize), not hand-crafted approximations — that's what keeps fidelity with zero
  operator running.
- **Keep the component CR as the source of truth** (the repo already fakes `Dashboard` + DSC/DSCI with
  `managementState`); in 3.x the desired state *is* the component CR + mgmtState.
- **Add a per-component `deploy_mode: manifests | operator`** to the release profile (default
  `manifests`). Pilot `operator` mode for the **dashboard** (the most 3.x-complex, BFF/modular
  component) as a higher-fidelity lane — behind a flag, and only after a spike proves the dashboard
  module operator runs in vanilla kind.
- **Do not plan to run the full platform (rhods) operator in kind.**

**Implication for the P1 spike.** "How do I deploy 3.x" splits into two org-independent sub-decisions,
both to resolve during the spike: (1) **standalone manifests vs module operator** (default manifests;
pilot operator for the dashboard), and (2) **which 3.x train/refs** (already in `releases/3.x.yaml`).


## 9. Evidence / sources

**Repo (current):** README.md:74-88 (rhoai-2.25 / notebooks v1.36.0); `components/deploy.py`
(single `--workbench-branch` knob); `components/03-kf-pipelines.yaml`,
`04-odh-dashboard.yaml`, `07-dsc-dsci.yaml`, `09-kf-notebooks/kustomization.yaml`,
`components/crds/`, `components/02-kyverno/`; the 3 workflows in `.github/workflows/`;
`components/ods-ci/test-variables.yml` + root `test-variables.yml`.

**RHOAI context (read-only):**
- Slack #wg-rhoai-odh-test-release-strategy — "A Product-centric Development Workflow for RHOAI"
  (collapsing ODH midstream → product-level integration from upstream; promotion gates + e2e
  coverage from RHOAIENG-24681 / "Bodies of Water").
- Confluence "RHOAI Z-stream Release Process" — 2.25.z / 3.3.z are the current EUS Z-streams;
  upstream→downstream cherry-pick flow; vLLM image source.
- Confluence "ODH Dashboard: Builds & Konflux Guide" — two image categories (main dashboard +
  modular-architecture modules); ODH vs RHOAI distributions; `BUILD_MODE`; monorepo; hermetic
  downstream builds.
- Confluence "02.2 - rhoai-test-flow" — the *official* Jenkins test flow (OpenShift-based). This
  kind repo is a **separate local/dev path**; nothing here forces changing it, but it's the
  reference for what "test a release" means at the product level.
- Jira RHOAIENG-32633 ("AI Pipeline" rename, targets 3.0); RHOAIENG-24681 (promotion gates).
