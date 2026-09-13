# Option A — Separate branches (`main` = 2.x, `odh-3.x` = 3.x)

**TL;DR:** Branch per release train. `main` stays the green 2.25.z baseline; a new `odh-3.x` carries the 3.x pins *and* is the only place free to restructure steps. Cheapest start, and the right container for the riskiest phase (the 3.x monorepo spike).

## Core argument (why A for *this* repo)

1. **The 3.x delta is partly *structure*, not just pins.** The 3.x dashboard is an npm-workspaces monorepo (Go BFFs + `BUILD_MODE`), not a new tag. The cypress workflow already says `main` "drifted; its npm-workspaces monorepo layout also broke the install" (`rhoai-in-kind-with-cypress.yaml:55`), so 3.x cypress likely needs a *different test-runner step*, not just a new `ref`; a branch lets `odh-3.x` change steps without 2.x CI tolerating a two-program shape.

2. **Zero risk to the working 2.x train.** This repo's most valuable property *today* is green 2.25.z CI, the baseline gating release work. Under A, `main` is untouched; `odh-3.x` can be red, mid-spike (the P1 dashboard retarget the doc calls "where most of the real work lives") without a 2.x PR or nightly at risk.

3. **The fork is cheap, and it mirrors the real topology.** Upstream/downstream already ship *branches per train* (2.25.z, 3.3.z), so the branch name *is* the version. `git branch odh-3.x main`, then only ~10 files diverge: `deploy.py:506`, `03-kf-pipelines.yaml:35`+env, `04-odh-dashboard.yaml:39,65,103-106`, `09-kf-notebooks/kustomization.yaml:34-35`, `07-dsc-dsci.yaml` (DSC 2.13.0 / CR 2.22.0 / mgmtStates), the 3 workflows' env/matrix/refs/prepull digests, 2 `test-variables.yml`. Everything else (kind, ArgoCD, Kyverno, Istio, cert-manager, oauth, MinIO, all of `deploy.py`) is shared.

## Concrete plan
- **Start:** `git branch odh-3.x` off `main` (split into `rhoai-2.x`+`rhoai-3.x` later only if 2.x must diverge). Use the scaffolded `releases/3.x.yaml` as the checklist; edit the pins above. **Don't touch** shared infra or any `.github/actions/*`.
- **Retarget the 3 workflows** on the branch (env/matrix/refs/prepull) — where A earns its keep for the cypress monorepo (restructure that job freely).
- **CI:** 2.x on `main` unchanged (PR+push-main+daily cron = release baseline); 3.x on `odh-3.x` PR+daily, "must-converge" (red OK in the spike). Routine bumps: 2.x → PR to `main`, 3.x → PR to `odh-3.x`.

## Honest tradeoffs
- **Buys:** risk-free 2.x isolation; per-version structural freedom; cheapest start.
- **Costs:** every shared-infra/`deploy.py`/action fix must land in **both** branches (2× work + drift); CI **doubles** once both run daily (ods-ci matrix ≈ 40 jobs × 3 suites); history splits, so "what differs" = `git diff odh-3.x main` (real files amid noise); lose clean A/B "same harness, two versions."
- **Main risk:** "shared infra stays identical" is enforced by *discipline*, not structure — 2.x can silently lose a fix, or 3.x can run on stale infra.

## Where I'm conceding (strongest point against A)
The doc's premise — *what differs is ~10 data fields, not logic or infra* — is correct, and C (one codebase + a ~40-line profile) is the **minimal** org to isolate exactly that: no duplicated infra, no cherry-picks. A buys that isolation **by duplicating the whole harness to protect ~10 files**; for routine pin bumps C does less work, and its two-file diff beats `git diff` across two trees.

**Mitigation:** treat A as the *temporary* container for the riskiest phase, and **plan to collapse it** — once 3.x is green, lift its *structural* deltas into a `variant`/hooks field *inside* the single `deploy.py` (open question #4) and converge on C, deleting the branch. I defend A only because the monorepo likely needs real step changes, the 2.x baseline must stay risk-free during the spike, and a branch is deletable later with zero downside.
