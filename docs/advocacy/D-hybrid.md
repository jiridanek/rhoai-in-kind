# Option D — Pragmatic hybrid: prove 3.x on a branch first, profile it after

## Core argument

The fork-prone "version surface" is ~9 data fields + 2 test-variable files — **data, not logic**. In
`components/deploy.py` the only version input is `--workbench-branch` (L148–153, consumed at L507);
everything else — Kyverno (L173), cert-manager, ArgoCD (L242), Istio, fake CRDs (L247),
api-extension (L274), MinIO (L375) — is version-independent and stays put. The ODH pins sit in four
YAMLs: `03-kf-pipelines.yaml` (targetRevision L35, image env L66–71), `04-odh-dashboard.yaml`
(targetRevision L39, image L65, oauth digests L103–104), `07-dsc-dsci.yaml` (DSC 2.13.0, CR 2.22.0,
mgmtStates L66–97), `09-kf-notebooks/kustomization.yaml` (kubeflow ref L34–35).

The dominant 2.x→3.x cost is the **dashboard-monorepo + CRD + test-suite retarget (P1)**, which you
pay under *any* option. `releases/` is explicitly "scaffold only — not yet consumed," and
`releases/3.x.yaml` is all TODO. So doing the profile refactor (P0) *first* means refactoring toward
unknowns and taking a regression risk on the working 2.x CI before 3.x even deploys.

**D sequences the risk before the refactor:** `git branch odh-3.x` edits only those ~9 fields, and
since all three workflows already expose `workflow_dispatch` `test_repo`/`test_ref` inputs, you can
point at 3.x test suites without editing a workflow line. The cypress workflow *already* checks out
the full dashboard monorepo and `npm ci`s at the root (`…-with-cypress.yaml` L52–63, L151–159) —
the "biggest retargeting cost" is already half-plumbed.

## Concrete plan

1. **Branch:** `git branch odh-3.x` from `main`; `main` stays 2.x, untouched, green.
2. **Edit pins in place** on the branch: 3.x targetRevision+images in `03`/`04`, 3.x
   DSC/CR/mgmtStates in `07`, 3.x kubeflow ref in `09`, 3.x `workbench_branch`/`NOTEBOOK_IMAGE_TAG`
   + prepull digests in the workflow env/matrix, 3.x keys in both `test-variables.yml`.
   **No `deploy.py` change** for a pin-only 3.x.
3. **De-risk P1** (dashboard `path`/monorepo, new CRDs, bring-your-own-id-connect) by running the
   three suites via `workflow_dispatch`; re-derive `notebook_image_tag`/prepull from a fresh run's
   cluster-logs (the workflow's own CAUTION says: don't guess).
4. **Profile-later:** when 3.x is green, do P0 *the same week* — lift the branch's proven pins into
   `releases/3.x.yaml`, wire `deploy.py --release` + the workflows to consume it, prove
   main+profile green, **delete the branch.**

## Honest tradeoffs

- **Buys:** a running 3.x in ~week 1; **zero added CI on `main`** (3.x is opt-in via branch/dispatch);
  the first 2.x↔3.x diff is a single `git diff main..odh-3.x` over a small surface.
- **Costs:** while the branch lives, shared-infra fixes get done twice (the exact A/B divergence tax),
  and "what changed" is a branch merge, not two clean profile files. CI doubles only if/when you
  promote to a matrix axis — a later P3 decision, made *after* 3.x is proven.
- **Main risk:** the spike becomes a permanent second line.

## Where I'm conceding

The strongest point against D is real: **as a steady state, C is strictly better** — D degrades into
Option A's trap if you never do the profile-later step, and the org doc's own verdict is C. My
mitigation: treat `odh-3.x` as a *timeboxed spike* with a hard merge-back-and-delete deadline; keep
its diff to the version fields only (infra fixes land on `main`, the branch re-bases); and commit to
the profile-later step — which the branch makes *cheaper and lower-risk* precisely because it hands
P0 a set of **known-good** 3.x values to validate against, not TODOs.
