# 3.x spike runbook — 3.3 EUS, upstream

Copy-paste procedure to bring up a 3.x stack. **Verified feasible in this environment**
(docker 6.0.2, kind v0.33.0, kubectl present; `deploy.py` is pure kubectl/kind — **no `oc`**
needed). Runs on a **separate, disposable** `kind` cluster: zero impact on the existing
`kubezoo-e2e-test` cluster or the remote OCP context. The `odh-3.x` branch is deletable.
Rollback at the end.

## Confirmed 3.3 refs (all verified against upstream, Sep 2025)
| Element | 3.3 value |
|---|---|
| ODH release | operator tag `v3.3.0` (clean release) |
| Dashboard (deploy) | `v3.3.1-odh` — *same* `manifests/rhoai/onprem` path as 2.x |
| Dashboard (cypress) | `v3.3.1-odh` |
| ods-ci | `release-3.3` branch |
| opendatahub-tests | `3.3` branch |
| DSPO / notebook-controller / fake-DSC versions | **resolve against the live cluster** (see step 6) |

## The spike
### 1. Branch from the 2.x baseline (`main`)
```
git checkout main && git checkout -b odh-3.x
```

### 2. Apply the 3.x refs — pick a scope
**A) Dashboard-only probe (recommended first step — lowest risk, highest signal).**
Keep 2.x DSPO/pipelines/notebooks; upgrade only the deployed dashboard. Two-line edit to
`components/04-odh-dashboard.yaml`:
- L39 `targetRevision: v2.37.1-odh` → `v3.3.1-odh`
- L65 `value: quay.io/opendatahub/odh-dashboard:v2.37.1-odh` → `...:v3.3.1-odh`
(The 2 new 3.x params vars — `kube-rbac-proxy`, `gateway-name` — come from the 3.x
`params.env` defaults automatically; no extra patch needed.)

**B) Full 3.x.** Additionally retarget:
- `components/03-kf-pipelines.yaml` — DSPO `targetRevision` (+ env image overrides)
- `components/09-kf-notebooks/kustomization.yaml` — kubeflow ref (2.x = `v1.10.0-5`)
- `components/07-dsc-dsci.yaml` — fake DSC/CR versions + mgmtStates
- the 3 workflows' test refs (ods-ci `release-3.3`, odh-tests `3.3`, cypress `v3.3.1-odh`)

### 3. Create the kind cluster
```
kind create cluster --config components/00-kind-cluster.yaml \
  --image docker.io/kindest/node:v1.34.11@sha256:44e222ee2132dab25ff87301682f89eb82c7880ea3a1bf543bfe9708fd08d67d
```

### 4. Deploy (~10-15 min)
```
python3 components/deploy.py --workbench-branch=v1.36.0   # 2.x notebooks ref; for full 3.x use the 3.x train ref
```

### 5. Verify
- `kubectl get pods -A` — are all components Ready?
- Dashboard: `kubectl -n redhat-ods-applications get pod -o wide`; confirm image is
  `odh-dashboard:v3.3.1-odh`; check it serves + the 2 params vars are honored.
- **Known-unknowns to resolve here (first minutes):** DSPO 3.x ref, notebook-controller
  `v1.10.0-N` (v1.10.0-6 has the "AI Pipeline" rename), fake DSC/CR versions → read from the
  deployed CRs / the `jupyter-minimal-notebook` imagestream.

### 6. (Optional) Run a suite
- **cypress**: `workflow_dispatch` with `test_repo=opendatahub-io/odh-dashboard`,
  `test_ref=v3.3.1-odh` (the monorepo checkout + `npm ci` are already half-plumbed).
- **ods-ci**: `release-3.3`; **odh-tests**: `3.3`.

## Rollback (fully reversible)
```
kind delete cluster kind
git checkout main && git branch -D odh-3.x
```

## Notes
- `deploy.py` does **not** create the cluster — step 3 must run first (cluster name `kind`).
- Network is required for image pulls (quay.io / docker.io).
- 3.x dashboard `params.env` adds `kube-rbac-proxy` (odh-kube-auth-proxy) + `gateway-name`
  vs 2.x; the 2.x oauth-proxy `images:` rewrites may need re-deriving for 3.x.
