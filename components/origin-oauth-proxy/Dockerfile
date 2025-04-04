# podman build -t quay.io/jdanek/origin-oauth-proxy components/origin-oauth-proxy
# kind load docker-image quay.io/jdanek/origin-oauth-proxy

FROM quay.io/openshift/origin-oauth-proxy@sha256:1ece77d14a685ef2397c3a327844eea45ded00c95471e9e333e35ef3860b1895

# login-url is where user's browser gets redirected to perform login
# the other urls are fetched by oauth-proxy backend from inside the cluster
ENTRYPOINT ["/usr/bin/oauth-proxy", "-login-url", "http://oauth-server.localhost/auth", "-redeem-url", "http://oauth-server.oauth-server.svc:8080/token", "-validate-url", "http://oauth-server.oauth-server.svc:8080/userinfo", "-openshift-review-url", "http://oauth-server.oauth-server.svc:8080/review"]
