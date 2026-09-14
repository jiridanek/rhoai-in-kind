# Patched oauth-proxy for the 3.x in-kind dashboard (browser OAuth)

The 3.x rhods-dashboard fronts its API with kube-rbac-proxy (token review, TLS-only),
which rejects unauthenticated browsers on every path including the SPA, so a browser can
never start the OAuth dance (chicken-and-egg). We put a patched openshift/oauth-proxy
sidecar in front of it (TLS 8443 -> http://localhost:8446 insecure kube-rbac-proxy port).

The existing Dockerfile in this directory is the **2.x** variant (image + fixed args).
The 3.x variant is **source-built** from openshift/oauth-proxy with three patches,
because the stock image cannot (a) forward the session token downstream, (b) survive the
kube-rbac-proxy TLS cert for localhost, and (c) hijack websocket upgrades.

## Upstream base

github.com/openshift/oauth-proxy @ bb5169e (master, "Merge pull request #374 ...disallow-open-redirects").
Apply oauth-proxy-3x.patch:

- oauthproxy.go — CheckRequestAuth accepts a raw client Bearer token; Authenticate forwards Authorization: Bearer <token> to the upstream. kube-rbac-proxy does the REAL token review for BOTH the cookie (browser) and client-Bearer (API/robot) paths. No -skip-auth-regex needed.
- http.go — ServeHTTPS forces NextProtos = ["http/1.1"]. Default oscrypto.SecureTLSConfig sets [h2, http/1.1]; when ALPN negotiates h2 the Go h2 ResponseWriter is not an http.Hijacker and every /wss/k8s/* websocket upgrade fails with 500.
- logging_handler.go — responseLogger (the -request-logging wrapper) implements Hijack() delegating to the wrapped writer. wsutil.go:137 checks w.(http.Hijacker) and answers 500 "Not a hijacker?" (16-byte body) otherwise.

## Build

    # from the patched source tree (upstream checkout + oauth-proxy-3x.patch applied)
    GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -o oauth-proxy-amd64 .
    podman build -f local.Dockerfile -t quay.io/jdanek/origin-oauth-proxy:patched .
    podman push quay.io/jdanek/origin-oauth-proxy:patched
    kind load docker-image quay.io/jdanek/origin-oauth-proxy:patched --name kind

local.Dockerfile is FROM scratch + the static binary (the stock image is a huge base;
scratch keeps kind load fast).

## Deployment

components/oauth-server/patch-dashboard.py rewrites the rhods-dashboard deployment:

- kube-rbac-proxy container: stays TLS on 8445 (its --listen-address is not a flag), plus an insecure port 8446 for the oauth-proxy upstream; args reset to the known-good full list.
- new oauth-proxy container on 8443 (the svc dashboard-ui targetPort), args:

    -provider openshift -skip-provider-button
    -login-url  https://oauth-server.127.0.0.1.sslip.io/oauth/authorize
    -upstream   http://localhost:8446
    -redeem-url http://oauth-server.127.0.0.1.sslip.io/token
    -pass-access-token -request-logging
    -client-id dsh-oauth-client -client-secret dsh-oauth-secret
    -cookie-secret 0123456789abcdef0123456789abcdef
    -https-address 0.0.0.0:8443
    -tls-cert /etc/tls/private/tls.crt -tls-key /etc/tls/private/tls.key

Then: kubectl rollout restart deploy/rhods-dashboard -n redhat-ods-applications

## Gotchas (all cost hours)

- -redeem-url is mandatory. Without it the openshift provider discovers the token endpoint from the k8s API server /.well-known/oauth-authorization-server, which vanilla k8s rejects 403 for system:anonymous -> login callback 500 "error redeeming code". Pin it to the in-kind oauth-server /token. Use http (port 80 via the istio gateway): the in-cluster gateway cert has no SAN for the sslip host, so https redemption fails x509.
- -login-url must point at the worktree oauth-server (components/oauth-server/oauth-server.go), which serves the login page, an /oauth/authorize alias, and /token. The /oauth/authorize path mirrors standard RHOAI (oauth-openshift.apps.<cluster>/oauth/authorize) so the cypress visitWithLogin URL-pattern check triggers the provider-link + credentials flow. Any username with password "password" works (admin-user, ldap-admin1/2, ldap-user1/2/9).
- -upstream http, not https. The dashboard cert has no localhost SAN; https to localhost:8445 fails x509. The insecure 8446 port still does the real token review (auth is on the proxy, not the transport).
- -cookie-secret fixed so signed in-memory session cookies survive pod restarts.

## Verified

components/oauth-server/e2e-full.sh (fresh cookie jar): 302 -> login 200 -> POST creds -> 307 callback w/ code -> redeem -> 302 -> / 200, REST /api/k8s/... 200, and /wss/k8s/... 101 Switching Protocols with live {"type":"ADDED",...} watch frames. Real Chrome shows the Projects page with no "issue fetching projects" banner. With this in place the cypress testWorkbenchImages.cy.ts spec and the ods-ci Elyra robot browser login both succeed (see docs/odh-3x-handoff.md).

