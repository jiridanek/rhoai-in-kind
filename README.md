## Local usage

```shell
podman machine set --rootful
podman machine start
kind create cluster

kubectl apply -k components/01-argocd

kubectl create namespace redhat-ods-applications
kubectl apply -f components/03-kf-pipelines.yaml

PASSWORD=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)
export ARGOCD_OPTS='--insecure --port-forward --port-forward-namespace argocd'
argocd login --insecure --username admin --password $PASSWORD
argocd cluster add kind-kind --core --yes
argocd app sync kf-pipelines
```
