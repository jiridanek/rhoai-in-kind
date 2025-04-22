# https://quay.io/repository/jdanek/origin-oauth-proxy?tab=builds

# podman build -t quay.io/jdanek/origin-oauth-proxy components/origin-oauth-proxy
# kind load docker-image quay.io/jdanek/origin-oauth-proxy

FROM quay.io/openshift/origin-oauth-proxy@sha256:1ece77d14a685ef2397c3a327844eea45ded00c95471e9e333e35ef3860b1895

# login-url is where user's browser gets redirected to perform login
# the other urls are fetched by oauth-proxy backend from inside the cluster

# cypress struggles with localhost
# cypress struggles with secure cookies with samesite restriction
#  https://github.com/cypress-io/cypress/issues/5895
#  https://github.com/cypress-io/cypress/issues/18690
#  https://www.tomoliver.net/posts/cypress-samesite-problem
# https://github.com/openshift/oauth-proxy/blob/3d12ccbee45c5d4bcea8c232867df58a60c4382b/README.md#L203
# ods-ci insists on https
ENTRYPOINT ["/usr/bin/oauth-proxy", "-login-url", "https://oauth-server.127.0.0.1.sslip.io/auth", "-redeem-url", "http://oauth-server.oauth-server.svc:8080/token", "-validate-url", "http://oauth-server.oauth-server.svc:8080/userinfo", "-openshift-review-url", "http://oauth-server.oauth-server.svc:8080/review", "-cookie-samesite", "none"]
