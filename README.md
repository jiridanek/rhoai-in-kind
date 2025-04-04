## Local usage

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
