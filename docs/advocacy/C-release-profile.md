# Option C — Single codebase + parameterized "release profile"

## Core argument — why C is right for *this* repo

The repo is already ~80% a profile; C completes that pattern instead of forking what should stay shared. The **entire** ODH-version surface is a small set of *data*, in exactly: one arg (`deploy.py:148` `--workbench-branch`, applied at `deploy.py:506-508` against `opendatahub-io/notebooks`); four kustomize/Argo files (`03-kf-pipelines.yaml:35,66-71`, `04-odh-dashboard.yaml:39,65,100-106`, `07-dsc-dsci.yaml:11-52,66-97,203-216`, `09-kf-notebooks/kustomization.yaml:34-35`); and three workflows carrying the test-suite refs + `WORKBENCH_BRANCH`/`NOTEBOOK_IMAGE_TAG` + prepull digests (`with-ods-ci.yaml:33,41,64-179,198`; `with-cypress.yaml:15,59`; `with-odh-tests:15,42`) plus two `test-variables.yml`. Everything else — kind v1.34.11, ArgoCD v3.5.1, Istio 1.26.2, cert-manager v1.18.2, api-extension, oauth-server, MinIO, coreDNS, plus all of `deploy.py`'s orchestration and test-runner steps — is version-**independent**. A/B fork that shared logic/infra too, making a 2.x↔3.x comparison an unviewable cross-branch diff. C isolates the actual variable: **the 2.x↔3.x delta is literally the diff of two ~50-line `releases/<name>.yaml` files** — reviewable, and scaling to N trains (3.4, 2.25.12) just means adding a file, not merging a branch.

## Concrete plan (2.x + 3.x under C)

The profiles already exist (`releases/2.25.z.yaml` filled, `releases/3.x.yaml` TODO); the work is making them *consumed*:
- **P0 (zero behavior change):** add a `--release` knob to `deploy.py` (default `2.25.z`) + a small loader; render the profile's pins into the 4 files. Argo refs via kustomize **overlays** under `releases/<name>/` (Option D) or a template; the git-remote refs in `09`; the fake DSC/CR/managementState in `07`. Workflows: add a `release` input that feeds `WORKBENCH_BRANCH`/`NOTEBOOK_IMAGE_TAG`, the 3 checkout refs, test-variables, and prepull_images. **Gate: all 3 workflows green on `main` with the 2.25.z default → 2.x byte-identical.**
- **P1 (the real cost):** fill `releases/3.x.yaml` and get `deploy.py --release 3.x` to bring up a 3.x stack. Hardest is the dashboard monorepo (`04-odh-dashboard.yaml:37,39`) plus any new fake CRDs / bring-your-own-id-connect. **Identical under A/B/C.**
- **P2:** point the 3 suites at 3.x refs; triage. **P3:** a `release` matrix axis (3.x manual/schedule first) + a sync linter.

## Honest tradeoffs

Buys: no infra/logic fork; a visible, diff-able version delta; N-train scaling; **opt-in CI cost** (3.x manual/schedule, not every PR); and a linter that automates the many "CAUTION: keep in sync" comments already scattered across the workflows. Costs: a **one-time P0 refactor touching every file holding a pin** (real churn to the working 2.x path, though gated zero-behavior-change), a new indirection layer, and **≈ +1× runner time** for a full 3.x matrix (kind bootstrap ~350s + per-test pulls).

## Where I'm conceding

The strongest point against C: **a profile file does not make a release *known-good by construction***. The ~9 fields are *correlated* (workbench tag ↔ image tag ↔ prepull digests ↔ DSPO pin) — the repo's own "CAUTION: keep in sync" comments prove it already bites — yet a single yaml can be **internally inconsistent** (one field bumped, its partner not): a failure mode a frozen per-version branch (A) simply can't produce. I concede C trades "known-good by construction" for "reviewable diff." **Mitigation:** (1) a sync-guard linter that cross-checks the correlated pins and fails CI on mismatch; (2) `default: true` on 2.25.z + the P0 gate keep the green path untouched; (3) schema requiring correlated fields to be set together, so a partial profile can't load. And because P1 (the 3.x dashboard retarget) dominates the cost under *every* option, C's extra cost is bounded and one-time — while A/B's divergence cost is open-ended.
