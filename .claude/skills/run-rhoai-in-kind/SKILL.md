---
name: run-rhoai-in-kind
description: Build, run, and drive rhoai-in-kind - spins up a local kind Kubernetes cluster running an OpenShift AI / Open Data Hub-like stack (dashboard, notebook controller, DSPO, Kyverno polyfills) and lets you interact with the real dashboard UI. Use when asked to run this project, bring up the local cluster, redeploy after a components/ change, take a screenshot of the dashboard, or verify a change against the real running stack instead of just reading CI logs.
---

This isn't a single app - it's CI infrastructure that recreates a local
kind cluster, deploys an ODH-Dashboard-like stack onto it via
`components/deploy.py`, and drives the resulting web UI with a Playwright
script (`.claude/skills/run-rhoai-in-kind/driver.mjs`). All paths below
are relative to the repo root.

## Prerequisites

macOS with Apple Silicon (this was verified on `darwin/arm64`; the CI
equivalent runs on `ubuntu-latest` and doesn't need any of the podman/
Rosetta steps below - see `.github/workflows/*.yaml` for that path).

```bash
# Podman machine, rootful, with Rosetta so amd64-only ODH images don't
# crash (SIGSEGV / lfstack) - one-time setup:
mkdir -p ~/.config/containers && printf '[machine]\nrosetta = true\n' >> ~/.config/containers/containers.conf
podman machine init --rootful --memory $((16 * 1024)) --cpus 4
podman machine start
```

```bash
kind version   # v0.32.0 verified working
kubectl version --client
python3 --version   # needs 3.13, per pyproject.toml requires-python
node --version   # v26.7.0 verified working even though CI pins Node 20 -
                 # this repo's own tooling has no Node-version-specific code
```

Python deps: `.venv/` already exists at repo root (uv-managed, `boto3`
for `deploy.py`'s MinIO/S3 bucket provisioning). If missing: `uv sync`.

## Setup / Build

No compile step. "Building" this project means recreating the cluster:

```bash
kind delete cluster --name kind   # only if one already exists
kind create cluster --config components/00-kind-cluster.yaml --image docker.io/kindest/node:v1.31.6
```

`kind create cluster` sets kubeconfig's current-context to `kind-kind`
as a side effect - verify rather than assume:

```bash
kubectl config current-context   # must print kind-kind
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'   # must be https://127.0.0.1:6443
```

**This kubeconfig has ~100 contexts, several of them real production
clusters.** Never assume the current-context is local. Prefer pinning
`--context kind-kind` on individual `kubectl`/`oc` calls over globally
switching context with `kubectl config use-context` (the latter mutates
shared state for every other shell/tool until something switches it
back - see [[cluster-context-safety]] memory). `components/deploy.py`
itself has no `--context` flag and relies on the ambient current-context,
which is why the explicit verification above matters before running it.

## Run (agent path)

Deploy the stack, then drive the resulting dashboard with the Playwright
script:

```bash
.venv/bin/python3 components/deploy.py --workbench-branch=v1.36.0
```

Takes several minutes (Kyverno, Istio, ArgoCD-synced ODH Dashboard,
DSC/DSCI, local-path storage check - see the `::group::` sections in its
output). Ends with the dashboard reachable at
`https://rhods-dashboard.127.0.0.1.sslip.io/`.

Then drive it:

```bash
cd .claude/skills/run-rhoai-in-kind
npm install                       # one-time: installs playwright
npx playwright install chromium   # one-time: downloads the browser binary
node driver.mjs login-screenshot [output.png]   # default: ./screenshots/dashboard.png
```

`driver.mjs` reads admin credentials from the repo root's
`test-variables.yml` (`OCP_ADMIN_USER` block: `adm-auth` /
`adminuser` / `adminuser-passwd`), launches headless Chromium with
`ignoreHTTPSErrors: true` (the oauth-proxy serves a self-signed cert),
submits the `/oauth/start` form, clicks the `adm-auth` identity-provider
link, fills the login form, waits for the "Data Science Projects" home
page element, and screenshots. One command, one function
(`login-screenshot`) today - it's a starting point, not a full REPL;
extend it with more `page.locator(...)` calls for whatever flow you
need to verify next, following the same pattern.

**For real feature verification** (not just "did it come up"), drive it
through the project's own vendored e2e suites instead of hand-rolling
more Playwright calls - they already exist and are more thorough:

```bash
# Cypress (odh-dashboard) - e.g. the workbench+PVC/volume-attach test:
git clone --branch v2.37.1-odh --depth 1 https://github.com/opendatahub-io/odh-dashboard.git odh-dashboard
cd odh-dashboard && npm ci --prefer-offline --no-audit
cd frontend
TERM=xterm-256color CY_TEST_CONFIG="$(pwd)/../../test-variables.yml" \
  npm run cypress:run -- --spec '**/workbenches/workbenches.cy.ts'
```

Results land in `odh-dashboard/frontend/src/__tests__/cypress/results/e2e/`
(`index.html` report; screenshots only on failure, video off by default
in this repo's CI config).

```bash
# ods-ci (robot framework) and opendatahub-tests (pytest) follow the
# same pattern as their CI steps in .github/workflows/rhoai-in-kind-with-
# ods-ci.yaml / -shiftleft.yaml - checkout at the pinned ref, install
# deps (poetry / uv), run against the same live cluster.
```

## Run (human path)

Open `https://rhods-dashboard.127.0.0.1.sslip.io/` in a real browser and
click "Log in with OpenShift" → `adm-auth` → `adminuser` /
`adminuser-passwd` (self-signed cert warning: click through it, same as
[[chrome-devtools-self-signed-cert-bypass]]). Tear down with
`kind delete cluster --name kind`.

## Test

See `## Run (agent path)`'s e2e section above - this project's "tests"
*are* driving the running app (cypress/ods-ci/opendatahub-tests), there's
no separate unit-test-only command. `python3 -m py_compile components/*.py`
is a fast sanity check after editing `deploy.py`, not a real test.

---

## Gotchas

- **`test-variables.yml`'s `TEST_USER` block (`AUTH_TYPE: foo-auth`) is
  not a real identity provider in this repo's local oauth-server setup.**
  The actual configured IDPs are `adm-auth` / `contributor-auth` /
  `ldap-provider-qe` (from `components/opendatahub-tests/openldap.yaml`).
  Use the `OCP_ADMIN_USER` block instead. Confirmed by `curl`-ing the
  oauth-server's actual login page and reading the rendered `<a>` links
  rather than guessing from the yaml.
- **npm's newer default script-allowlist silently skips Cypress's own
  postinstall** (`npm warn install-scripts ... cypress@... (postinstall:
  node index.js --exec install)`), which is what downloads the Cypress
  binary. `npm ci` still exits 0. Check with `npx cypress verify` before
  assuming the binary is there - if missing, `npx cypress install`.
- **Playwright needs its browser binary downloaded separately from the
  npm package** (`browserType.launch: Executable doesn't exist at
  .../chrome-headless-shell`) - `npm install playwright` alone isn't
  enough, always follow with `npx playwright install chromium`.
- **`ignoreHTTPSErrors: true` on the Playwright context** is the
  equivalent of manually clicking through Chrome's self-signed-cert
  interstitial - much simpler than the chrome-devtools MCP click-through
  approach when scripting rather than driving interactively.
- **`kind create cluster` changes kubeconfig's current-context as a
  side effect.** If the workflow is delete-then-recreate-then-deploy (the
  normal local loop), this often makes an explicit context switch
  unnecessary - just verify with `kubectl config current-context`
  immediately before `deploy.py` rather than assuming either way.
- **The dashboard's default StorageClass comes from kind itself**
  (`standard`, provisioner `rancher.io/local-path`, annotated
  `is-default-class: "true"` at cluster-creation time) - `deploy.py`
  does NOT need to install a separate provisioner or create a
  specially-named StorageClass; dashboard/cypress code looks the default
  class up dynamically via that annotation, not by a hardcoded name.

## Troubleshooting

- **`locator.click: Timeout ... waiting for getByRole('link', { name:
  'foo-auth' })`**: wrong IDP name - see the `test-variables.yml` gotcha
  above, use `adm-auth`.
- **`kubectl get storageclass` shows two classes, only one
  `(default)`**: harmless if intentional (e.g. testing an older
  `deploy.py` revision that still installs `rancher/local-path-
  provisioner`'s own manifest) - only the one flagged `(default)`
  matters; the extra one is inert unless something references it by name.
- **`Error from server (Forbidden)` on ordinary `kubectl get`
  commands**: current-context is a remote cluster, not `kind-kind`. Run
  `kubectl config current-context` and fix before continuing - don't
  assume permission errors mean something is broken locally.
