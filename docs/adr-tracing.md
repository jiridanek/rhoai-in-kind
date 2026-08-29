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

## Update (2026-08-30): gateway added, one hypothesis corrected, one new problem found

Implemented the tail-sampling gateway proposed below, plus structured-log parsing for the two
kubeflow/odh notebook controllers. Two corrections to the record above, both found by verifying
live rather than trusting a plausible-sounding first read:

- **The "ArgoCD/Kyverno can't reach `host.docker.internal`" hypothesis was wrong.** A live test
  (`kubectl run --rm -i --image=busybox nslookup host.docker.internal`) showed regular,
  non-hostNetwork pods resolve it fine via CoreDNS forwarding. Kyverno's tracing was already
  working before this change - confirmed via a real distributed trace with both a
  `kyverno-admission-controller: POST` root span and an `apiserver: PUT .../leases/{:name}`
  child span from one lease-renewal call. The gateway was still worth adding, for a different
  reason: `tail_sampling` makes one keep/drop decision per trace ID, so every participant of a
  shared trace like that one needs to flow through the *same* collector instance, or the two
  ends' decisions could disagree and orphan half the trace.
- **ArgoCD's own tracing is confirmed broken, root cause still unknown.** `ARGOCD_SERVER_OTLP_ADDRESS`
  is correctly set in `argocd-server`'s environment (checked via `kubectl exec ... env`), and it
  was rolled out fresh after the ConfigMap change, but it emits zero traces - Aspire's
  `argocd-server` resource shows "No traces found" even under live, unpaused, freshly-reloaded
  data - and its logs never mention otlp/otel/tracing at all, unlike Kyverno's explicit
  `traces export: ...` failure logging when something is actually wrong. Not investigated
  further this pass.

**Gateway build note**: kube-apiserver's static pod runs in the node's own network namespace
with the node's own `/etc/resolv.conf`, not CoreDNS (confirmed live:
`podman exec kind-control-plane getent hosts kubernetes.default.svc.cluster.local` fails) - a
`*.svc.cluster.local` name doesn't resolve there even though the ClusterIP itself does (kube-proxy's
iptables NAT is node-wide). Pinned the gateway Service to a fixed ClusterIP
(`10.96.200.200`) instead of relying on DNS for the one caller that needs it.

**Verified working, with hard numbers** (`otelcol_receiver_accepted_spans`/`_log_records` and
`_exporter_sent_*` counters scraped directly off the gateway/DaemonSet's own Prometheus
endpoints, not just eyeballing the UI): the gateway received 199,923 spans and successfully
forwarded 177,453 of them; `tail_sampling` evaluated 45,307 traces and kept 24,050 (~53%),
dropping the rest as single-span noise - a real, working flood fix, not just a config that
parses. The DaemonSet's log pipeline received and forwarded 72,323/72,323 log records with zero
drops after adding the new parsing operators.

**Structured-log parsing for kubeflow's `notebook-controller` and `odh-notebook-controller-manager`**
(the two controllers the user specifically asked to add): inspected their actual log output
live rather than guessing.
- `odh-notebook-controller-manager` emits one JSON object per line (zap JSON encoder) -
  straightforward `json_parser`.
- kubeflow's `notebook-controller-deployment` emits zap's **console** encoder instead:
  tab-separated `<ts>\t<LEVEL>\t<logger-or-message>[\t<message>][\t{json fields}]`, with an
  inconsistent field count (a logger-name column appears only for named sub-loggers, with no
  marker distinguishing its presence) - handled with a `regex_parser` that extracts
  timestamp/severity and, if present, a trailing JSON fields blob, deliberately leaving the
  human-readable message text unsplit rather than guessing wrong.
- A `router` operator dispatches on the first character of the line (`^\{` vs a tab-separated
  header) rather than hardcoding container/pod names, so this also covers any other component
  using either format.
- Found and fixed two real bugs while verifying end-to-end rather than trusting the config once
  it stopped erroring: (1) the JSON path had no `severity` mapping and used the default
  `parse_to: body` (which just re-serializes the parsed map back to JSON-looking text - Aspire
  showed no visible difference from unparsed output even though parsing technically "succeeded"),
  fixed by adding `parse_to: attributes` and mapping `level`; (2) both controllers name their
  single container `manager` (confirmed via `kubectl get deploy ... -o jsonpath=
  '{.spec.template.spec.containers[*].name}'` on both), so the existing
  `service.name = k8s.container.name` logic collapsed them into one indistinguishable Aspire
  resource - fixed by adding a second `resource` processor step that upserts `service.name` from
  `k8s.deployment.name` when present (a no-op for anything not Deployment-owned).

**New limitation found, distinct from the ones above**: even with parsing fixed and confirmed
correct at the collector level (72,323/72,323 received/sent, verified via the DaemonSet's own
Prometheus metrics), the two controllers' actual log *entries* were never observed in Aspire's UI
- not because the pipeline dropped them, but because Aspire's structured-logs view appears to
share one fixed-size global ring buffer across every source in the cluster (repeatedly observed
capped at exactly 220 rows, on both the traces and structured-logs pages independently). In a
cluster where a handful of chatty components (kube-apiserver, Kyverno, CoreDNS) emit far more
volume than a mostly-idle controller, the idle one's few log lines get evicted from that shared
buffer almost immediately - filtering to its resource afterward can't recover data that's already
gone. This is an Aspire configuration/scale limitation (there may be an env var to raise the
cap), not a bug in the collector pipeline itself, and wasn't fixed in this pass.

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
