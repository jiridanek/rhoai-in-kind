#!/bin/bash
# End-to-end verification of the in-kind dashboard browser-OAuth path
# (patched oauth-proxy sidecar + fake oauth-server). Verifies: login 302 flow,
# session cookie, REST via the proxy, and the k8s websocket upgrade (101 + data).
#
# Usage: e2e-full.sh [dashboard-url] [username] [password]
#   defaults: https://rhods-dashboard.127.0.0.1.sslip.io admin-user password
set -u
DASH="${1:-https://rhods-dashboard.127.0.0.1.sslip.io}"
USER_NAME="${2:-admin-user}"
USER_PASS="${3:-password}"
J=$(mktemp)
WS_OUT=$(mktemp)
trap 'rm -f $J $WS_OUT' EXIT
echo "== login =="
LOC=$(curl -sk -c $J -b $J -o /dev/null -w "%{redirect_url}" $DASH/)
echo "redirect: $LOC"
curl -sk -b $J -c $J -o /dev/null "$LOC"
A=$(curl -sk -b $J -c $J -o /dev/null -w "%{redirect_url}" --data "username=$USER_NAME&password=$USER_PASS" "$LOC")
cb=$(curl -sk -b $J -c $J -o /dev/null -w "%{http_code} -> %{redirect_url}" "$A")
echo "callback: $cb"
echo "== dashboard GET / =="
curl -sk -b $J -o /dev/null -w "%{http_code}\\n" $DASH/
echo "== REST watch prerequisite =="
curl -sk -b $J -o /dev/null -w "%{http_code}\\n" "$DASH/api/k8s/apis/project.openshift.io/v1/projects?limit=250"
echo "== WS upgrade (10s timeout; expect 101) =="
timeout 10 curl -sk -b $J -D - -o $WS_OUT -H "Connection: Upgrade" -H "Upgrade: websocket" -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" "$DASH/wss/k8s/apis/project.openshift.io/v1/projects?watch=true" 2>&1 | head -6
echo "== first bytes of ws stream =="
head -c 300 $WS_OUT; echo
