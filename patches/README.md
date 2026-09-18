# Local (do-not-commit-upstream) patches for odh-dashboard-3x

The in-kind cypress run needs two intentional local modifications to the
odh-dashboard-3x checkout (pinned v3.3.1-odh). The /tmp/odh-dashboard-3x tree
is NOT a git checkout, so these edits cannot be diffed in place - after any
fresh checkout of the dashboard, run:

    python3 patches/apply-odh-dashboard-3x-local-patches.py /path/to/odh-dashboard-3x

The script is idempotent (skips already-applied patches).

## Patch 1 - packages/cypress/cypress/utils/discoverTestPatterns.ts

Upstream runs execSync('npm query .workspace --json') unguarded; the repo-pinned
npm (10.9.2) exits 1 silently, which crashes the cypress.config load before any
spec runs. Wrap in try/catch and return [] (explicit --spec invocations do not
depend on discovered patterns).

## Patch 2 - packages/cypress/cypress/tests/e2e/dataScienceProjects/workbenches/testWorkbenchStatus.cy.ts

In-kind cold pull of the ~3.2GB workbench image from quay.io exceeds the
upstream 120s Running-wait budget (observed 2-3 min pull + scheduling). Bump
120000 -> 600000.
