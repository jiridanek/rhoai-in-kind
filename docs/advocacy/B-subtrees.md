# Option B — Per-Version Subtrees in `main`

## Core argument

The fork-prone "version surface" is **not a flat list of scalars** — it is a **coherent set of Kubernetes manifests that must stay mutually consistent**: the fake `07-dsc-dsci.yaml` (DSC `managementState`s ↔ component-CR version ↔ the fake CRDs in `components/crds/`), the Argo apps `03-kf-pipelines.yaml` / `04-odh-dashboard.yaml` (each `targetRevision` ↔ its image overrides ↔ its patches), and the `09-kf-notebooks` kustomization (git refs ↔ patches). That unit is a **directory you `kubectl apply -k`**, not a row of unrelated fields. A per-version subtree (`variants/2.x/`, `variants/3.x/`) *is* that unit, so "what changed between 2.x and 3.x" becomes a plain directory diff, not two flat profile files you then map back onto kustomize.

B does **not** fork the ~600-line `components/deploy.py` or the shared infra — only the ~5 manifest-bearing files (`03`, `04`, `07`, `09`, `crds`) plus the two `test-variables.yml` move per variant. `deploy.py` keeps every shared-infra step (kind / cert-manager / istio / argocd / kyverno / minio / oauth, the `_deploy` orchestration, the `deploy-stuff` action) untouched; the **only** edit is pointing the Argo / DSC / CRD / notebook applies at `variants/<v>/`. B forks *data*, not *logic*. The 3.x dashboard's structurally different npm-workspaces layout **confirms** this: `variants/3.x/odh-dashboard/` can simply **be a different shape** with no schema to encode it.

## Concrete plan

1. **Split the tree.** `components/` keeps shared infra + `deploy.py`. Create `variants/2.x/` holding the 2.x `03` / `04` / `07` / `09` / `crds` + `test-variables.yml` + a `tests.yaml` (suite refs `release-2.25` / `v2.37.1-odh` / SHA `94670b3…`, prepull digests, `notebook_image_tag` `2025b-v1.36`, `workbench_branch` `v1.36.0`).
2. **Make `deploy.py` variant-aware.** Add `--variant 2.x` (env `VARIANT`, default `2.x`). Shared steps untouched; the Argo / DSC / CRD / notebook steps read `variants/<v>/`. `deploy-stuff` gains a `variant` input.
3. **Wire the workflows.** Each of the 3 workflows takes a `variant` input (default `2.x`), threads it into `deploy-stuff`, and selects `variants/<v>/tests.yaml` for suite refs + test-variables + prepull.
4. **Author `variants/3.x/`** (the P1 dashboard/CRD retarget — independent of org choice); start manual / `workflow_dispatch`, promote to schedule.
5. **Add a thin sync check** asserting within-variant consistency (branch ↔ tag ↔ digests).

2.x stays the default, so existing green CI is behaviorally unchanged.

## Honest tradeoffs

Buys: a single branch/history, both versions testable from one CI, and the 2.x↔3.x delta as a directory diff. Costs: `deploy.py` becomes variant-aware (a real coupling point — its apply-list must change if the per-variant file set grows); the version-shaped Kyverno policies must be triaged per-variant in P1; and CI cost is +1× per variant if matrixed.

## Where I'm conceding

**Strongest point against B:** the repo is already moving *toward* one-source-of-truth (env `WORKBENCH_BRANCH`, `workflow_dispatch` inputs, kustomize patches, the `releases/<name>.yaml` scaffold) — and the `CAUTION: keep in sync` comments prove scalar pins (branch / tag / digest) drift. A naive subtree **duplicates** those scalars (each variant carries its own), putting each pin in two homes (variant dir + workflow env).

**Mitigation:** co-locate *every* pin for a version inside its variant dir — manifest pins in the kustomize/Argo files, scalar/test pins in one `variants/<v>/release.yaml` — so nothing is duplicated *across* the shared tree; run the same thin linter *per variant*. B then differs from C only in that the coherent manifest set lives in a diffable directory instead of a template that reconstructs it.
