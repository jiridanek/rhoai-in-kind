# ADR: Observability tracing for rhoai-in-kind

## Status

Partially implemented. `deploy.py`'s own tracing (Section "What's merged") is live on `main`.
The cluster-native pieces (Section "What's built but unmerged") exist as commits on the local
`jd-logfire-tracing` branch only - not pushed, not applied to any cluster in CI.

## Context

`components/deploy.py` runs ~25 sequential steps (each wrapped in `gha_log_group()`), shelling
out via `sh()` for `kubectl`/`argocd`/`curl`/etc., against a real kind cluster. Total runtime is
several minutes. The only built-in visibility was GitHub Actions' collapsed `::group::` log
folding - no timing breakdown, no span hierarchy, no way to compare runs, and no visibility at
all into what the *cluster itself* (kube-apiserver, ArgoCD, Kyverno) was doing while a step
waited.

We wanted:

1. A waterfall view of `deploy.py`'s own steps/commands, usable both locally (a live TUI/console
   view while iterating) and exportable to a real trace viewer.
2. The option to also see what's happening *inside* the cluster during a slow step - is
   kube-apiserver slow, is a Kyverno admission webhook the bottleneck, is ArgoCD stuck - without
   adding this as a mandatory dependency or slowing down every deploy run.
3. Zero cost when nobody's using it: CI doesn't have a collector listening, so none of this
   should add latency, dependencies, or flakiness to the normal CI path.

## Decision

### `deploy.py` script-level tracing (merged, PR #102)

Instrument `gha_log_group()` and `sh()` with OpenTelemetry spans via **Pydantic Logfire**, kept
strictly optional:

- `logfire`/`opentelemetry-exporter-otlp-proto-grpc`/`opentelemetry-instrumentation-botocore`
  live in a `pyproject.toml` `[project.optional-dependencies] tracing` extra, not a hard
  dependency - a plain `uv sync` (what CI does) never installs any OTel package at all.
- `src/rhoai_in_kind/__init__.py` defines a `Tracer` protocol (`NullTracer` by default,
  `LogfireTracer` once `configure_tracing()` in `deploy.py` finds the extra installed) and
  `sh()`/`gha_log_group()` call through it - so the instrumented functions never import
  `logfire` directly and are safe to call whether or not tracing is configured.
- Three independent, always-safe-to-combine output channels: GHA `::group::` markers (always
  on), a local Logfire console span tree (on when `CI` is unset), and OTLP export (only when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set). Because Logfire's own OTLP exporter is HTTP-only, a
  manual gRPC exporter is built when `OTEL_EXPORTER_OTLP_PROTOCOL=grpc` is requested (needed for
  collectors, including the Aspire dashboard, that only speak gRPC).
- One root span per `deploy()` run, so every step nests under a single trace instead of each
  appearing as an unrelated top-level trace.

Chosen picture: Logfire over raw `opentelemetry-sdk` for its minimal boilerplate and pretty
local console tree; over MLflow's tracing for being OTel-native rather than ML-run-centric; over
Dagger for not requiring a different execution model for the whole script. See project memory
`logfire-otel-gotchas`/`tracing-optional-dependency-di` for the detailed API gotchas hit along
the way (HTTP-only exporter, `{var}` template vs literal span name, signal-specific
`OTEL_EXPORTER_OTLP_*_PROTOCOL` override, etc.).

### Cluster-native tracing (built, verified live, not yet merged)

Four opt-in, independently-toggleable pieces, none wired into the default `components/deploy.py`
flow or any CI workflow (CI has no collector listening, so this is local-debugging-only today):

1. **kube-apiserver native tracing** (`components/13-apiserver-tracing/`,
   `components/00-kind-cluster-tracing.yaml`) - kube-apiserver's own
   `--tracing-config-file` flag (`apiserver.config.k8s.io/v1beta1` `TracingConfiguration`,
   100% sampling), pointed at `host.docker.internal:18889` (the Aspire dashboard's gRPC OTLP
   port). Requires both kind's `extraMounts` (file on the node) and kubeadm's
   `apiServer.extraVolumes` (mounted into the apiserver container's own mount namespace) - a kind
   config change, so it needs a fresh cluster (or a live static-pod-manifest patch via
   `docker cp`, see memory `kind-live-patch-static-pods`, for an already-running one).
2. **OTel Collector DaemonSet** (`components/14-otel-collector/`) - `kubelet_stats` receiver for
   node/pod/container CPU/RAM, a `file_log` receiver for container stdout/stderr, and a separate
   single-replica `k8s_events` Deployment for cluster Events (kept separate from the DaemonSet to
   avoid duplicate events across nodes, since no leader election is configured).
3. **ArgoCD tracing** (`components/01-argocd/kustomization.yaml`) - one `argocd-cmd-params-cm`
   ConfigMap key (`otlp.address`) that `argocd-server`/`argocd-repo-server`/
   `argocd-application-controller` all read.
4. **Kyverno tracing** (`components/02-kyverno/kustomization.yaml`) - `--enableTracing`/
   `--tracingAddress`/`--tracingPort` args added to all 4 controller Deployments.

**Live verification (2026-08-30, this cluster)**: with only piece 1 actually applied to a
running cluster (via the earlier live static-pod patch), kube-apiserver traces streamed into a
freshly-started Aspire dashboard continuously and were genuinely informative - e.g. a
`PUT .../mutatingwebhookconfigurations/{:name}` call showed a full phase breakdown
(`authentication` → `audit` → `impersonation` → `priorityandfairness` → `authorization` →
`Update` → `GuaranteedUpdate etcd3` → etcd RPC → `SerializeObject`), with real numbers (35.45ms
total, 24.34ms of it in the etcd-write phase). **Limitation found**: apiserver tracing does not
break out individual admission-webhook call latency as separate child spans - webhook time is
folded into the coarse `Update`/`GuaranteedUpdate etcd3` phase, so it tells you "storage/webhook
phase is slow" but not "which specific webhook."

Pieces 2-4 were **not** applied to the live cluster during that verification (their config only
exists in git on the unpushed branch) - ArgoCD/Kyverno app-level traces and the collector's
metrics/logs/events were confirmed absent (only one resource, `apiserver`, showed up in Aspire),
which is expected given they were never `kubectl apply`'d there, not a sign of malfunction.

## Known UX problems (user-reported, 2026-08-30, live cluster)

Live use surfaced two real usability problems with the current design, beyond the
already-noted "no per-webhook breakdown" limitation - these are not hypothetical:

1. **kube-apiserver tracing at 100% sampling floods the viewer.** Kyverno's controllers alone
   generate a constant background stream of `authentication`/lease-renewal/
   `subjectaccessreviews`/policy-CRUD calls against the apiserver - every one becomes a full
   trace at `samplingRatePerMillion: 1000000`. In a busy cluster this buries the traces someone
   actually opened the dashboard to find (a slow admission call, a stuck ArgoCD sync) under a
   wall of routine control-loop noise. The apiserver's `TracingConfiguration` has no per-path
   sampling/exclusion rules (see `k8s.io/apiserver` tracing docs) - the practical fix would be
   dropping the global sample rate (e.g. to 1-10%) and accepting that most control-loop chatter
   won't be captured, or filtering in the collector between the apiserver and the viewer (not
   currently in this design - the apiserver points directly at Aspire with no
   collector/processor in between it).
2. **`/structuredlogs` is neither structured nor correlated.** The OTel Collector's `file_log`
   receiver + `container` operator parses only the container-log-file *envelope* (timestamp,
   stream, pod/namespace/container labels via `k8s_attributes`) - it does not parse the log
   *payload* as JSON, so arbitrary app stdout lines land as opaque strings. Worse, since these
   are ordinary container stdout lines (not emitted through an OTel logging bridge), they carry
   no `trace_id`/`span_id` at all - there is no way for Aspire to link a log line to the apiserver
   trace that was active when it was written, even if both exist in the viewer at the same time.
   Fixing this for real would need either (a) a `transform`/`json_parser` operator in the
   collector config for logs that are themselves JSON-formatted, and (b) trace-context
   propagation from whatever's emitting the log (out of reach for third-party binaries like
   kube-apiserver/Kyverno/ArgoCD unless they already support OTel log export - which none of the
   four cluster-native pieces above currently use for logs, only traces/metrics).

Net effect: the cluster-native tracing pieces are real and technically working (per the
kube-apiserver verification above), but as currently configured the resulting operator
experience is noisy and disconnected - closer to a proof that the wiring works than a tool
someone would reach for to debug a real slow-deploy incident today. Tightening sampling and
adding log-payload parsing/correlation are the concrete next steps if this is to be relied on,
not merely demoed.

## Consequences

- Nobody pays for this who doesn't opt in: no new hard dependencies, no CI behavior change, no
  cluster-config change to the default `components/00-kind-cluster.yaml`/`deploy.py` flow.
- Local debugging gets a genuinely useful, real-data view into both the deploy script's own
  timing and (once the cluster-native pieces are actually applied) the cluster's internal
  request lifecycle - not merely a demo/proof-of-concept.
- The cluster-native pieces require a real OTLP collector reachable at
  `host.docker.internal:18889` (documented pattern: the .NET Aspire dashboard, chosen for its
  dual gRPC+HTTP OTLP support) - anyone using them locally needs that running first, and the
  hardcoded host/port would need to become configurable before this could be anything other than
  a personal local-debugging setup.
- Aspire's dashboard has no persistent storage (in-memory, and always run with `--rm`) - any
  traces are lost the moment the container stops. This is inherent, not a bug to fix.
- The cluster-native pieces are unverified as a *set* (only kube-apiserver tracing has been
  confirmed live) and unverified against CI entirely - merging them would need at minimum a
  fresh full local deploy + inspection pass before trusting the ArgoCD/Kyverno/collector config
  as correct.

## Alternatives considered

- **Raw `opentelemetry-sdk`** instead of Logfire: more boilerplate for provider setup, no
  built-in pretty console renderer; rejected for developer-experience reasons, not correctness.
- **MLflow tracing**: ML-run-centric data model, poor fit for a general deploy-script/infra trace.
- **Dagger**: pretty TUI, but would mean restructuring `deploy.py` around Dagger's own execution
  model rather than adding instrumentation to the existing script.
- **Jaeger / otel-tui** as the local viewer instead of the Aspire dashboard: Aspire won on having
  both gRPC and HTTP OTLP ingestion in one binary plus a clean web UI; kept as the documented
  default, not an exclusive requirement - anything OTLP-compatible works.
