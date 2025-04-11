This code is based on a starter project available at
https://github.com/kubernetes/sample-apiserver/blob/master/README.md

## Running it stand-alone

During development it is helpful to run sample-apiserver stand-alone, i.e. without
a Kubernetes API server for authn/authz and without aggregation. This is possible, but needs
a couple of flags, keys and certs as described below. You will still need some kubeconfig,
e.g. `~/.kube/config`, but the Kubernetes cluster is not used for authn/z. A minikube or
hack/local-up-cluster.sh cluster will work.

Instead of trusting the aggregator inside kube-apiserver, the described setup uses local
client certificate based X.509 authentication and authorization. This means that the client
certificate is trusted by a CA and the passed certificate contains the group membership
to the `system:masters` group. As we disable delegated authorization with `--authorization-skip-lookup`,
only this superuser group is authorized.

1. First we need a CA to later sign the client certificate:

   ``` shell
   openssl req -nodes -new -x509 -keyout ca.key -out ca.crt
   ```

2. Then we create a client cert signed by this CA for the user `development` in the superuser group
   `system:masters`:

   ``` shell
   openssl req -out client.csr -new -newkey rsa:4096 -nodes -keyout client.key -subj "/CN=development/O=system:masters"
   openssl x509 -req -days 365 -in client.csr -CA ca.crt -CAkey ca.key -set_serial 01 -sha256 -out client.crt
   ```

3. As curl requires client certificates in p12 format with password, do the conversion:

   ``` shell
   openssl pkcs12 -export -in ./client.crt -inkey ./client.key -out client.p12 -passout pass:password
   ```

4. With these keys and certs in-place, we start the server:

   ``` shell
   ./api-extension --secure-port 8443 --v=7 \
      --client-ca-file ca.crt \
      --kubeconfig ~/.kube/config \
      --authentication-kubeconfig ~/.kube/config \
      --authorization-kubeconfig ~/.kube/config
   ```

   The first kubeconfig is used for the shared informers to access
   Kubernetes resources. The second kubeconfig passed to
   `--authentication-kubeconfig` is used to satisfy the delegated
   authenticator. The third kubeconfig passed to
   `--authorized-kubeconfig` is used to satisfy the delegated
   authorizer. Neither the authenticator, nor the authorizer will
   actually be used: due to `--client-ca-file`, our development X.509
   certificate is accepted and authenticates us as `system:masters`
   member. `system:masters` is the superuser group such that delegated
   authorization is skipped.

5. Use curl to access the server using the client certificate in p12 format for authentication:

   ``` shell
   curl -fv -k --cert-type P12 --cert client.p12:password \
      https://localhost:8443/apis/wardle.example.com/v1alpha1/namespaces/default/flunders
   ```

   Or use wget:
   ``` shell
   wget -O- --no-check-certificate \
      --certificate client.crt --private-key client.key \
      https://localhost:8443/apis/wardle.example.com/v1alpha1/namespaces/default/flunders
   ```

   Note: Recent OSX versions broke client certs with curl. On Mac try `brew install httpie` and then:

   ``` shell
   http --verify=no --cert client.crt --cert-key client.key \
      https://localhost:8443/apis/wardle.example.com/v1alpha1/namespaces/default/flunders
   ```

6. Use kubectl or oc with a hand-crafted kubeconfig to authenticate

```

```