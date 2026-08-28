# Kubernetes ↔ OpenShift version matrix

Which Kubernetes minor version ships inside each OpenShift release. Used when
picking a kind `node_image` for this repo's local/CI cluster, so that
behavior differences between kind and "real" OpenShift CI stay predictable.

| OpenShift version | Kubernetes version | Notes |
|---|---|---|
| 4.12 (EUS) | 1.25 | |
| 4.13 | 1.26 | |
| 4.14 (EUS) | 1.27 | |
| 4.15 | 1.28 | |
| 4.16 (EUS) | 1.29 | |
| 4.17 | 1.30 | |
| 4.18 (EUS) | 1.31 | |
| 4.19 | 1.32 | |
| 4.20 (EUS) | 1.33 | |
| 4.21 | 1.34 | matches this repo's pinned `kindest/node:v1.34.11` (see below) |
| 4.22 | 1.35.x | confirmed via real CI job telemetry (`test-pytest-cnv-4.22-*` etc. on actual 4.22.8/4.22.9 clusters running Kubernetes v1.35.6), not just public release notes |
| 5.0 (in active nightly development) | 1.36.x | confirmed via `sd-srep-releases` Slack channel `ClusterImageSet` churn |

## Why this matters here

Kubernetes **v1.35.0** (released 2025-12-17) changed kubelet's `Created`/
`Started` container-lifecycle event messages from `"Created container: <name>"`
/ `"Started container <name>"` to a bare `"Container created"` /
`"Container started"` — the container name is dropped from the message
entirely (it only survives in `event.involvedObject.fieldPath`).

odh-dashboard's Workbench-status "Progress" tab identifies the oauth-proxy
container by string-matching `event.message` for `oauth-proxy`, which can
never match the new message format — so the corresponding progress steps get
stuck `Pending` forever. This is not fixed upstream as of this writing.

That's why this repo's kind `node_image` is pinned to `v1.34.11` (see the
comment above `node_image:` in each `.github/workflows/rhoai-in-kind-*.yaml`)
rather than a newer kind default — `v1.34.11` is the latest kind node image
still on the pre-v1.35 kubelet message format, and conveniently matches what
OpenShift 4.21 itself ships. Full investigation: issue #98.

**Before bumping `node_image` past v1.34.x again**, either wait for an
upstream odh-dashboard fix, or confirm the target Kubernetes version is
still below 1.35.
