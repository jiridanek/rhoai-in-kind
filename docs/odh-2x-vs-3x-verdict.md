# 2.x + 3.x organization — verdict

Synthesis of the four steelman briefs in [`docs/advocacy/`](advocacy/): each advocate argued its own
option to the wall, verified every pin against the live files, and stated its single strongest
concession. **They converge.**

## The one finding that reframes the decision

**The org choice is a *secondary* decision.** The dominant cost of "test 3.x as well as 2.x" is the
**P1 3.x retarget — the dashboard npm-workspaces monorepo + any new CRDs / bring-your-own-id-connect
+ the 3.x test-suite curation** — and it is **identical under every option** (all four say this).
So "how to organize the repo" is a smaller question than "what does 3.x cost," and the org answer
mostly determines *ongoing maintenance*, not *initial effort*.

## Side-by-side (from the briefs)

| Dimension | **A** branches | **B** subtrees | **C** release profile | **D** hybrid (branch→profile) |
|---|---|---|---|---|
| Forks shared infra / deploy logic? | **Yes** (whole harness duplicated) | No (only 5 manifest files + 2 test-vars move) | No | No (after the spike) |
| "What changed 2.x↔3.x" = | `git diff` across 2 trees (~10 real files + noise) | a directory diff | a diff of two ~50-line YAMLs | branch diff during spike → profile diff in steady state |
| Time to **first** 3.x run | **fastest** (edit ~10 pin files on a branch; no deploy.py change) | medium (variant-aware deploy.py + `variants/2.x` first) | slower (P0 refactor first) | **fastest for the spike**, then C |
| Long-term divergence | **high** (cherry-pick both; drift) | low–med (two-homes scalar drift unless co-located + linted) | low (one profile/train + linter) | low **after** convergence |
| CI cost (3.x matrixed) | ~2× | +1× per variant | +1× (opt-in) | +1× after convergence |
| Add a new train (3.4, 2.25.12) | a new branch | a new dir | **a new file** | a new file (post-convergence) |
| Known-good-by-construction | **yes** (frozen branch) | partial (a dir can be internally inconsistent) | no (a yaml can be inconsistent → linter) | yes during the spike |
| Fits the repo's existing direction | neutral | partial (kustomize-native) | **strongest** (already ~80% a profile) | **strongest short-term** |
| Main risk | shared-infra drift (enforced by discipline, not structure) | deploy.py variant-awareness + two-homes drift | one-time P0 refactor churn + internal inconsistency | **the spike becomes a permanent 2nd line** |

## The convergence (the actual answer)

Read the four "where I'm conceding" sections and they say the same thing:

- **A** (branches): *"A = right **starting** org; C = right **steady-state** org."* The branch is a
  temporary container for the riskiest phase; **plan to collapse it.**
- **D** (hybrid): prove 3.x on a **throwaway branch** (de-risk P1), then lift the *proven* pins into
  C's profile **and delete the branch.**
- **B** (subtrees): converges with C — "B differs from C only in that the coherent manifest set
  lives in a diffable **directory** instead of a **template**."
- **C** (profile): the **steady-state** recommendation; concedes a profile isn't known-good-by-
  construction (a frozen branch's one real advantage) and mitigates with a sync-guard linter.

**So the decision is not "A vs B vs C vs D" — it's a sequence:**

> **Spike on a throwaway `odh-3.x` branch (A/D) to de-risk the org-independent P1 cost, then
> converge on the release-profile (C) as the steady state and delete the branch.**

This ordering is strictly better than any single option: the branch *protects* the green 2.x
baseline during the spike **and** makes P0 *cheaper* (it hands the profile a set of **known-good**
3.x values to validate against instead of TODOs), and you end at the org all four advocates agree
is the best steady state.

## Recommended plan (concrete)

> **Command-ready:** the exact, verified copy-paste steps (branch → refs → `kind create` →
> `deploy.py` → verify → rollback) are in [`docs/3x-spike-runbook.md`](3x-spike-runbook.md).

1. **De-risk now (the spike, ~1 wk, zero risk to 2.x).** `git branch odh-3.x`. On it, fill
   `releases/3.x.yaml`'s concrete refs (dashboard **`v3.3.1-odh`** candidate; confirm the notebooks
   3.x train, DSPO `main`/`stable` — there's **no `stable-3.x` branch** — and kubeflow
   `v1.10.0-N`) and edit the ~10 pin files **in place** (`03`/`04`/`07`/`09`, the 3 workflows'
   env/matrix/refs, 2 `test-variables.yml`). **No `deploy.py` change** is needed for a pin-only 3.x.
   Use the existing `workflow_dispatch test_repo`/`test_ref` to try the 3.x test suites **without
   editing a workflow line.** The cypress workflow *already* checks out + `npm ci`s the full
   dashboard monorepo, so the biggest P1 cost is partly pre-plumbed. If the spike shows 3.x needs a *structural* change (e.g. a different cypress test-runner **step** for the monorepo — A's strongest point), capture it as a `variant`/hooks field in the single `deploy.py` (eval §7 Q4) rather than forking — which is exactly why you spike on a branch *first* and converge *after*. The spike also resolves the **operator / deploy-mode axis** (eval §8): apply the 3.x components' *standalone* manifests directly (the default — the official `DEPLOY_RHODS_OPERATOR=False` mode) vs. optionally running the 3.x dashboard **module operator** for higher fidelity. That axis is orthogonal to the org choice and is *part* of this spike.
2. **Converge to C (~0.5–1 d, once 3.x is green).** Do P0: wire `deploy.py --release` + the 3
   workflows to read the profile (Argo refs via kustomize **overlays** under `releases/<name>/`),
   with **2.25.z as `default: true`** so the green 2.x path is byte-identical. Add the **sync-guard
   linter** (cross-check the correlated pins; fail CI on mismatch). **Delete `odh-3.x`.**
3. **Ongoing.** A new release train = a new ~50-line profile file. 3.x CI = manual/schedule + a
   smoke subset first, promoted to the full matrix once stable.

## The one residual fork: B vs C as the steady-state container

Once you've converged to "one codebase + a per-version surface," the only open choice is *how* that
surface is represented:

- **C (profile YAML + kustomize overlays):** one source of truth per train; the Argo refs are
  *generated* by overlays under `releases/<name>/`. Most reviewable; N-train scaling; but a profile
  can be internally inconsistent (→ linter) and the Argo files are reconstructed, not the raw
  manifests.
- **B (per-version directory of the real manifests):** the manifests live as-is in `variants/<v>/`;
  more kustomize-native (no reconstruction); but `deploy.py` becomes variant-aware and the scalar
  pins (branch/tag/digests) need co-location + a linter to avoid two-homes drift.

**C is the better default** (the repo is already ~80% a profile; it avoids deploy.py
variant-awareness and two-homes drift). The *one* argument for B: if the 3.x dashboard monorepo
needs a structurally different manifest **directory** that's awkward to template, use **B for that
component only** (a C-with-a-B-for-the-dashboard hybrid) rather than templating it.

## Still-open decision inputs (unchanged from the eval doc §7)
1. **Which 3.x target** — 3.3 EUS (recommended, mirrors 2.25.z) vs latest y-stream; candidates now
   concrete in `releases/3.x.yaml`.
2. **Upstream vs downstream** — recommend start upstream (`opendatahub-io`, no new creds).
3. **CI cost appetite** — 3.x manual/schedule + smoke subset first, full matrix later.

## Sources
- `docs/advocacy/A-separate-branches.md`, `B-subtrees.md`, `C-release-profile.md`, `D-hybrid.md`
- `docs/odh-2x-vs-3x-organization.md` (version surface, 3.x delta, phased plan, decision inputs)
- `releases/2.25.z.yaml` (filled) + `releases/3.x.yaml` (concrete candidates)
