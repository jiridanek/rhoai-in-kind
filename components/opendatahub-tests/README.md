OpenDataHub-Tests is a collection of e2e tests for OpenDataHub.

The trouble with it stems from tight integration with OpenShift in the test code.

First, the tests insist on using `oc login`, which means that the flow has to be supported.
Normal `kube-apiserver` lacks the `/.well-known/oauth-authorization-server` endpoint.
After some back and forth with a helpful chatbot, I turned to nginx to implement it and
reverse-proxy everything else to the real kube-apiserver.
This is essentially the same as our culler implementation in code-server and rstudio workbenches.

Second, the tests use the `project` openshift CR, but that's nothing new.

## NGINX

```shell
# Make sure paths in nginx.conf to certs are correct relative to the mount point
# Example: If nginx.conf is in current dir, and certs in ./nginx_certs
# Put the absolute path in nginx.conf or adjust the mount below

# Assuming nginx.conf is in the current directory ./
# Assuming certs are in ./nginx_certs/
podman run --rm --name nginx-kube-proxy \
  --network="host" \
  -v $(pwd)/nginx.conf:/etc/nginx/nginx.conf:ro \
  -v $(pwd)/nginx-certs:/path/to/your/nginx_certs:ro \
  --entrypoint /bin/sh \
  docker.io/library/nginx:latest -c 'nginx -c /etc/nginx/nginx.conf' 
  # Note: --network="host" makes Nginx directly use the host network, easily reaching 127.0.0.1:6443
  # Ensure /var/log/nginx exists or adjust log paths in config
```

```shell
niginx -c components/opendatahub-tests/nginx.conf
```

### Check it works

```shell
curl -k https://127.0.0.1:8443/.well-known/oauth-authorization-server
curl -k https://127.0.0.1:8443/version
```

```shell
oc login https://127.0.0.1:8443 --insecure-skip-tls-verify=true -u bef -p lek
oc login https://127.0.0.1:8443 --certificate-authority=$(pwd)/nginx_certs/nginx.crt  -u bef -p lek
```
