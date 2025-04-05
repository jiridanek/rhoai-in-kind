Start KinD (Kubernetes in Docker) single-node cluster, install the ODH components that concern the IDE team, and run some tests.

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
   Don't know yet, should not be too hard to fake the detection in notebook-controller
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

Out-of-date, see .github/workflows/rhoai-in-kind.yaml

```shell
podman machine set --rootful --memory $((16 * 1024)) --cpus 4
podman machine start
kind create cluster --config components/00-kind-cluster.yaml

kubectl apply -k components/01-argocd

kubectl create namespace redhat-ods-applications

PASSWORD=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)
export ARGOCD_OPTS='--insecure --port-forward --port-forward-namespace argocd'
argocd login --core
argocd cluster add kind-kind --yes

kubectl apply -f components/03-kf-pipelines.yaml
argocd app sync kf-pipelines
```
