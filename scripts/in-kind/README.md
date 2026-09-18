# In-kind operational scripts

Saved copies of the /tmp/kf3x helpers used to run + diagnose the in-kind 3.x probe.
They are machine-local (absolute /tmp paths) but stable for this probe layout.

| File | Purpose |
|---|---|
| run-cy.sh | Cypress runner: env for the workbench e2e specs (admin/password htpasswd login, probe KUBECONFIG, cy-test-config.yaml, chrome). Usage: `script -q /dev/null bash run-cy.sh <spec-name>.cy.ts` (the `script` wrapper supplies the pty cypress chrome needs). |
| cy-test-config.yaml | CY_TEST_CONFIG values (APPLICATIONS_NAMESPACE=redhat-ods-applications, empty S3 buckets). |
| make-probe-kc.py | Builds .kubeconfig-probe (htpasswd cluster-admin SA) from probe-ca.b64 + probe-token.env. |
| kerneltest.yaml | Minimal pod running the amd64-only KFP pipeline-runtime image - the Rosetta ipykernel deadlock repro. |
| kready3.py | Runs an ipykernel start + wait_for_ready(480s) inside the kerneltest pod; prints the timed verdict line. |
| wchancmd.sh | Dumps the wchan/State of every ipykernel thread - shows all threads parked in rt_mutex_schedule under Rosetta. |
| fulllogin2.sh | curl walkthrough of the browser login chain (authorize -> callback -> _oauth_proxy cookie -> 200) for debugging auth without a browser. |
