#!/bin/bash
# In-kind cypress run: workbench control/status specs via the new mesh path
set -x
cd /tmp/odh-dashboard-3x/packages/cypress
export PATH="/tmp/odh-dashboard-3x/ocwrap:$PATH"
export KUBECONFIG=/tmp/rhoai-odh3x/.kubeconfig-probe
export CYPRESS_CACHE_FOLDER=/tmp/cypress-cache
export MODULE_FEDERATION_CONFIG="[]"
export BASE_URL="https://rhods-dashboard.127.0.0.1.sslip.io"
export ADMIN_USER_USERNAME="admin"
export ADMIN_USER_PASSWORD="password"
export ADMIN_USER_LOGIN_METHOD="htpasswd"
export TEST_USER_3_USERNAME="ldap-user2"
export TEST_USER_3_PASSWORD="password"
export TEST_USER_3_LOGIN_METHOD="htpasswd"
export CY_TEST_CONFIG=/tmp/kf3x/cy-test-config.yaml
export CY_RETRY=0
export CYPRESS_DEFAULT_COMMAND_TIMEOUT=60000
node ../../node_modules/cypress/bin/cypress run -b chrome --spec "cypress/tests/e2e/dataScienceProjects/workbenches/$1"