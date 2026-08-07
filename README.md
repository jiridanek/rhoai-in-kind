Start KinD (Kubernetes in Docker) single-node cluster, install the ODH components that concern the IDE team, and run some tests.

Specifically, the components deployed are:

1. (ODH) Dashboard
2. (ODH) Notebook Controller
3. Datascience Pipelines Controller

The conspicuously missing component is of course the ODH Platform Operator.

The deployed Kubernetes manifests are taken directly from individual components' repositories, and the images in the cluster tend to be `:latest`-tagged builds from OpenShift CI.

## Prerequisites

See .github/workflows/rhoai-in-kind.yaml

## Obstacles this project overcomes

There are various Kubernetes environments where the components could be installed and test be then executed.

| OpenShift feature                        | OCP Local | OpenShift HCP (Hypershift)         | Microshift  | OKD                      | Vanila Kubernetes (KinD) |
|------------------------------------------|-----------|------------------------------------|-------------|--------------------------|--------------------------|
| Enable/disable integrated image registry | OK        | may not be reenabled once disabled | not present | OK                       | not present              |
| Integrated OAuth for oauth-proxy         | OK        | OK                                 | not present | requires rh subscription | not present              |
| SCC, RunAsNonRoot                        | OK        | OK                                 | OK          | OK                       | not present              |
| ca-service operator                      | OK        | OK                                 | ?           | OK                       | not present              |
| Istio and Kserve operators               | OK        | OK                                 | ?           | requires rh subscription | not present              |
| Project                                  | OK        | OK                                 | OK          | OK                       | not present              |
| Route                                    | OK        | OK                                 | different   | OK                       | not present              |
|                                          |           |                                    |             |                          |                          |

This repository focuses on KinD, which is a vanilla Kubernetes.
Therefore, what's missing from OpenShift and is required needs to be poly-filled in.

### How to overcome these issues?

1. Integrated image registry
   Our notebook-controller handles missing internal image registry; operating without internal image registry is an OpenShift AI feature.
2. oauth-proxy
   On okd it's necessary to use unauthenticated image, it can be substituted with kustomize

   On kubernetes it is necessary to also fake /.well-known/oauth endpoint and the users.user.openshift.io resource

   Dashboard uses the special (openshift-only) ~ user instead of the standard SelfSubjectAccessReview in one place.
   Additionally, Dashboard inspects OpenShift Groups to determine if the user is an admin or not.

   It is possible to implement and deploy a kubernetes API extension server and implement the user.openshift.io/v1/users/~ endpoint, already did that
3. RunAsNonRoot prevents running openshift workloads using openshift deployment manifests on kubernetes, because openshift automatically runs some workloads as nonroot while kubernetes requires specifying uid explicitly

   This concerns the ca-service operator, that can be run on Kubernetes, but tweaks are necessary.

   Either change user in extra layer in Dockerfile (I did that) or use Kyverno to either remove RunAsNonRoot, or set UID in the deployment the operator spawns.
4. Service mesh and Kserve operators are not necessary for Dashboard+Pipelines+Workbenches, so I did not investigate

   In brief, the problem is that these are available in redhat-operators OLM catalog which is only for paying customers

   To expose services to the outside world, I am using a minimal Istio install with the Gateway API.
   Any OpenShift route that actually needs to be exposed requires manually creating a Gateway API equivalent next to it to be actually exposed.

5. Project and Route (and ProjectRequest and User)

   These are required for the ODH Dashboard to function.
   Namespace alone will not suffice, a Project must be present.

   I tried spoofing stuff with the API extension server, but so far did not make it work.
   I can make the Dashboard usable enough for running the Elyra integration test already, but I can't run the (selected, workbench focused) Dashboard e2e tests ok Kubernetes yet.

   CRDs that only need to be present (CRUD operations on them) but need not be functional, can be implemented with a fake CRD.

## Local usage

Might get out-of-date, see .github/workflows/rhoai-in-kind.yaml for authoritative steps.

For `rhoai-2.25`, use [notebooks tag v1.36.0](https://github.com/opendatahub-io/notebooks/releases/tag/v1.36.0).
This is what went into the [corresponding ODH release](https://github.com/opendatahub-io/opendatahub-community/issues/183#issuecomment-3351838012)

```shell
# On Apple Silicon, enable Rosetta so the VM can run the amd64-only images (see note below).
# Rosetta is set via containers.conf (there is no `podman machine` CLI flag); it is the
# default on recent Podman — check with `podman machine inspect --format '{{.Rosetta}}'`.
# Enable it once if needed, before creating the machine:
mkdir -p ~/.config/containers && printf '[machine]\nrosetta = true\n' >> ~/.config/containers/containers.conf

podman machine init --rootful --memory $((16 * 1024)) --cpus 4
podman machine start
kind create cluster --config components/00-kind-cluster.yaml --image docker.io/kindest/node:v1.31.6

python3 components/deploy.py --workbench-branch=v1.36.0
```

> **Apple Silicon (arm64) note:** several images deployed here are published for `amd64`
> only (e.g. `api-extension`, the data-science-pipelines-operator). Under plain QEMU
> emulation their Go binaries crash at startup (`lfstack.push invalid packing` /
> `SIGSEGV` in `asm_amd64.s`). The fix is to enable **Rosetta 2** in the Podman machine,
> which translates amd64 correctly:
>
> - Rosetta is enabled via `[machine] rosetta = true` in
>   `~/.config/containers/containers.conf` (there is no `podman machine` CLI flag for it).
>   On recent Podman this is the default — check with `podman machine inspect --format '{{.Rosetta}}'`,
>   so hand-editing the config is often unnecessary.
> - Applying it to an **existing** machine only needs a **restart**, not a recreate:
>   `podman machine stop && podman machine start` (the `podman machine rm` is not required —
>   a restart re-provisions the Rosetta share and preserves your kind cluster).
> - Verify inside the VM: `podman machine ssh "cat /proc/sys/fs/binfmt_misc/rosetta"` should
>   report `enabled`.
>
> With Rosetta on, the amd64 images run as-is. As an alternative you can build `api-extension`
> natively for arm64:
> `podman build --platform linux/arm64 -t quay.io/jdanek/api-extension:latest -f components/api-extension/Dockerfile components/api-extension/` then `kind load docker-image quay.io/jdanek/api-extension:latest`.
>
> See [macOS Podman + Rosetta setup](https://github.com/opendatahub-io/notebooks/blob/main/docs/macos-podman-rosetta.md).

What does it do? This, among other things, in order to setup argocd access

```shell
PASSWORD=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)
export ARGOCD_OPTS='--insecure --port-forward --port-forward-namespace argocd'
argocd login --core
argocd cluster add kind-kind --yes

kubectl apply -f components/03-kf-pipelines.yaml
argocd app sync kf-pipelines
```

### Troubleshooting

Setting up the environment using this repo requires fast internet connection, otherwise things tend to timeout.

If you're getting timeouts from `kubectl apply`, increase the timeout encoded in the URL.

If you're getting timeouts while syncing ArgoCD applications, try increasing the `git clone` timeout in components/01-argocd/gittimeoutconfig.yaml.
We will have the ability to do shallow clones in ArgoCD 3.0.

### DNS: `*.sslip.io` hostnames don't resolve (macOS)

Services are exposed under [sslip.io](https://sslip.io) wildcard hostnames such as
`minio.apps.127.0.0.1.sslip.io`, which are supposed to resolve to `127.0.0.1`.
If `curl -k https://minio.apps.127.0.0.1.sslip.io` hangs or `deploy.py` fails in
`create_buckets()` with `NameResolutionError` / `EndpointConnectionError` — while
the cluster gateway is actually up — the problem is host DNS resolution, not the
cluster.

Two common macOS causes:

1. **A per-domain resolver in `/etc/resolver/` points at a local DNS that isn't running.**
   A file like `/etc/resolver/127.0.0.1.sslip.io` containing `nameserver 127.0.0.1`
   routes every `*.127.0.0.1.sslip.io` lookup to `127.0.0.1:53`. If you don't have a
   local resolver (dnsmasq/CoreDNS) listening there, resolution fails.
2. **DNS-rebinding protection** in Tailscale MagicDNS or some corporate/VPN resolvers,
   which drops answers pointing to a loopback address.

Diagnostic commands (macOS):

```shell
# What the system resolver (curl/python/boto3) actually returns — empty means it refuses the name
dscacheutil -q host -a name minio.apps.127.0.0.1.sslip.io

# Direct query, bypassing /etc/resolver overrides (sslip.io should answer 127.0.0.1)
nslookup minio.apps.127.0.0.1.sslip.io

# Inspect resolver scopes and per-domain nameservers
scutil --dns
ls -la /etc/resolver/ && cat /etc/resolver/*

# Prove the gateway works by bypassing DNS entirely (403 from MinIO = reachable)
curl -k --resolve minio.apps.127.0.0.1.sslip.io:443:127.0.0.1 https://minio.apps.127.0.0.1.sslip.io/

# Is a local resolver actually listening on :53?
sudo lsof -nP -iUDP:53 -iTCP:53
```

Fixes:

- If you rely on a local sslip.io resolver, make sure it is running.
- Otherwise remove the stale override so normal DNS (which resolves sslip.io to
  `127.0.0.1`) is used, and flush the cache:

  ```shell
  sudo rm /etc/resolver/127.0.0.1.sslip.io
  sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder
  ```

- If Tailscale is intercepting DNS: `tailscale set --accept-dns=false`.

#### Local `sslip.io` resolver via dnsmasq (macOS)

The most robust setup is a local dnsmasq that maps the whole wildcard to loopback —
it works offline, is fast, and sidesteps rebinding filters. This is the setup this
repo was developed with:

```shell
brew install dnsmasq

# Homebrew's prefix differs by arch (/opt/homebrew on Apple Silicon, /usr/local on Intel).
BREW_PREFIX="$(brew --prefix)"

# 1. Map every *.127.0.0.1.sslip.io host to 127.0.0.1.
#    `brew services` starts dnsmasq with `-7 "$BREW_PREFIX/etc/dnsmasq.d",*.conf`,
#    so any *.conf here is loaded automatically (no conf-dir edit needed).
echo 'address=/.127.0.0.1.sslip.io/127.0.0.1' > "$BREW_PREFIX/etc/dnsmasq.d/sslip.conf"

# 2. Route *.127.0.0.1.sslip.io lookups to the local resolver
echo 'nameserver 127.0.0.1' | sudo tee /etc/resolver/127.0.0.1.sslip.io

# 3. Start dnsmasq (needs sudo to bind port 53)
sudo brew services start dnsmasq
```

Verify:

```shell
dscacheutil -q host -a name minio.apps.127.0.0.1.sslip.io   # should print 127.0.0.1
```

The usual failure mode is simply that the dnsmasq service isn't running (e.g. after
a reboot if it wasn't enabled): `sudo brew services start dnsmasq` fixes it.
