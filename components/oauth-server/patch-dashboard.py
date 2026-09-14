#!/usr/bin/env python3
"""Add an oauth-proxy in front of the dashboard's kube-rbac-proxy (3.x browser login).

- kube-rbac-proxy: the 3.x odh-kube-auth-proxy is TLS-only (--listen-address is not a
  flag), so it stays TLS but moves 8443 -> 8445. Its args are reset to the known-good
  full list (TLS 8445 + cert args + token-review config + X-Auth-Request-User). The
  API-token path (real token review) is unchanged.
- oauth-proxy (new container, 8443 TLS): browser OAuth login (fake oauth-server); with
  -pass-access-token it forwards the session's K8s SA token (or a client Bearer token)
  over HTTPS to the kube-rbac-proxy (-ssl-insecure-skip-verify; the upstream cert is the
  dashboard cert, not for 'localhost'), which does the real validation.
- dashboard svc targetPort 8443 now lands on the oauth-proxy.

The quay.io/jdanek/origin-oauth-proxy:patched image is built from upstream
openshift/oauth-proxy @ bb5169e + the patches in components/origin-oauth-proxy/
(oauth-proxy-3x.patch + local.Dockerfile; see README-3x-patch.md):
- CheckRequestAuth accepts a raw client Bearer token; Authenticate forwards the
  session access token as Authorization downstream (kube-rbac-proxy does the real
  token review for both cookie and client-Bearer paths).
- ServeHTTPS forces NextProtos=[http/1.1]: the k8s websocket proxy (wsutil) hijacks
  the connection, which Go HTTP/2 ResponseWriters do not support (500 otherwise).
- responseLogger (request-logging wrapper) implements Hijack() and delegates to the
  underlying writer; without it every /wss request fails with "Not a hijacker?".
"""
import json, subprocess, sys, tempfile, os

def kubectl(*a):
    return subprocess.run(["kubectl", "-n", "redhat-ods-applications", *a],
                          capture_output=True, text=True)

o = kubectl("get", "deploy", "rhods-dashboard", "-o", "json")
if o.returncode != 0:
    sys.exit("get failed: " + o.stderr)
d = json.loads(o.stdout)
pod = d["spec"]["template"]["spec"]
containers = pod["containers"]

KRP_ARGS = [
    "--secure-listen-address=0.0.0.0:8445",
    # HTTP (no TLS) listen so the oauth-proxy can reach it over localhost without the
    # dashboard-cert/localhost SAN mismatch. kube-rbac-proxy still does the real token
    # review on this port (auth is on the proxy, not the transport).
    "--insecure-listen-address=0.0.0.0:8446",
    "--upstream=http://localhost:8080",
    "--config-file=/etc/kube-rbac-proxy/config-file.yaml",
    "--tls-cert-file=/etc/tls/private/tls.crt",
    "--tls-private-key-file=/etc/tls/private/tls.key",
    "--auth-header-fields-enabled=true",
    "--auth-header-user-field-name=X-Auth-Request-User",
    "--auth-header-groups-field-name=X-Auth-Request-Groups",
    "--proxy-endpoints-port=8444",
    "--v=10",
]

for c in containers:
    if c["name"] == "kube-rbac-proxy":
        c["args"] = list(KRP_ARGS)
        ports = c.get("ports") or []
        for p in ports:
            if p.get("containerPort") in (8443, 8445) and p.get("name") in ("dashboard-ui", "internal"):
                p["containerPort"] = 8445
                p["name"] = "internal"
        if not any(p.get("containerPort") == 8445 for p in ports):
            ports.insert(0, {"containerPort": 8445, "name": "internal", "protocol": "TCP"})
            c["ports"] = ports

oauth = {
    "name": "oauth-proxy",
    "image": "quay.io/jdanek/origin-oauth-proxy:patched",
    "imagePullPolicy": "IfNotPresent",
    "args": [
        "-provider", "openshift",
        # 302 unauthenticated browser requests straight to the login URL (the mock
        # /auth) instead of rendering the provider-button sign-in page. Required for
        # the Elyra/cypress browser login flow.
        "-skip-provider-button",
        # Redirect unauthenticated browsers to the mock oauth-server authorize
        # path, mirroring standard RHOAI (oauth-openshift.apps.<cluster>
        # /oauth/authorize) so the cypress visitWithLogin URL-pattern check
        # triggers the provider-link + credentials login flow.
        "-login-url", "https://oauth-server.127.0.0.1.sslip.io/oauth/authorize",
        # Patched oauth-proxy: CheckRequestAuth accepts a raw client Bearer token and
        # Authenticate forwards "Authorization: Bearer <token>" downstream, so the
        # kube-rbac-proxy does the real token review for BOTH the cookie (browser)
        # and client-Bearer (API) paths. No -skip-auth-regex needed.
        # HTTP (no TLS) to the kube-rbac-proxy insecure port: avoids the dashboard-cert
        # / 'localhost' SAN mismatch that broke the https://localhost:8445 upstream.
        "-upstream", "http://localhost:8446",
        # Token redemption endpoint, pinned to the in-kind oauth-server. Without it
        # the openshift provider discovers it from the k8s API server
        # (/.well-known/oauth-authorization-server), which vanilla k8s rejects 403.
        # HTTP (port 80 via the gateway): the in-cluster gateway cert has no SAN for
        # the sslip host, so https redemption fails x509 validation.
        "-redeem-url", "http://oauth-server.127.0.0.1.sslip.io/token",
        "-pass-access-token",
        "-request-logging",
        "-client-id", "dsh-oauth-client",
        "-client-secret", "dsh-oauth-secret",
        "-cookie-secret", "0123456789abcdef0123456789abcdef",
        "-https-address", "0.0.0.0:8443",
        "-tls-cert", "/etc/tls/private/tls.crt",
        "-tls-key", "/etc/tls/private/tls.key",
    ],
    "ports": [{"containerPort": 8443, "name": "dashboard-ui"}],
    "volumeMounts": [{"name": "proxy-tls", "mountPath": "/etc/tls/private"}],
}
containers = [c for c in containers if c["name"] != "oauth-proxy"]
containers.append(oauth)
pod["containers"] = containers
d["status"] = {}
out = os.environ.get("DASHBOARD_PATCH_OUT") or (tempfile.mkdtemp() + "/rhods-dashboard-patched.json")
with open(out, "w") as f:
    json.dump(d, f, indent=2)
print("saved", out)
print("containers:", [(c["name"], [(p.get("name"), p.get("containerPort")) for p in c.get("ports", [])]) for c in containers])
print("apply with: kubectl apply -f " + out)
