#!/usr/bin/env python3
"""Re-apply the intentional local modifications to an odh-dashboard-3x checkout.

The in-kind cypress run needs two changes that must NOT go upstream (see
docs/odh-3x-handoff.md, session 17). The /tmp/odh-dashboard-3x tree is not a git
checkout, so these edits cannot be diffed in place - this script re-applies them
to a fresh v3.3.1-odh checkout. Idempotent: already-applied changes are skipped.

Usage: python3 apply-odh-dashboard-3x-local-patches.sh /path/to/odh-dashboard-3x
"""
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/odh-dashboard-3x"

# --- Patch 1: discoverTestPatterns.ts ------------------------------------------
# Upstream: execSync('npm query .workspace --json') runs unguarded; the repo-pinned
# npm (10.9.2) exits 1 silently, which crashes the cypress.config load before any
# spec runs. Wrap in try/catch and return [] (explicit --spec invocations do not
# depend on discovered patterns).
P1_PATH = ROOT + "/packages/cypress/cypress/utils/discoverTestPatterns.ts"
P1_NEW = '''const getWorkspacePackages = (): WorkspacePackage[] => {
  try {
    const stdout = execSync('npm query .workspace --json', { encoding: 'utf8' });
    return JSON.parse(stdout);
  } catch {
    // `npm query .workspace` requires an npm build that supports it; on other
    // versions (e.g. the repo-pinned npm 10.9.2) it exits 1 silently. Explicit
    // --spec invocations do not depend on discovered patterns, so degrade
    // gracefully instead of crashing the whole cypress.config load.
    return [];
  }
};
'''

# --- Patch 2: testWorkbenchStatus.cy.ts ----------------------------------------
# In-kind cold pull of the ~3.2GB workbench image from quay.io exceeds the
# upstream 120s Running-wait budget (observed 2-3 min pull + scheduling).
# Bump to 600s. Do NOT commit upstream.
P2_PATH = (ROOT +
           "/packages/cypress/cypress/tests/e2e/dataScienceProjects/"
           "workbenches/testWorkbenchStatus.cy.ts")
P2_OLD = "notebookRow.expectStatusLabelToBe(NotebookStatusLabel.Running, 120000);"
P2_NEW = ("          // in-kind: the workbench image is pulled from quay.io on first use\n"
          "          // (pre-loaded into kind where possible); allow up to 10m to reach Running\n"
          "          notebookRow.expectStatusLabelToBe(NotebookStatusLabel.Running, 600000);")


def patch1():
    src = open(P1_PATH).read()
    if "return [];" in src and "npm query .workspace" in src:
        # heuristic: already wrapped
        if re.search(r"try \{[^}]*npm query .workspace", src, re.S):
            print("patch1: already applied")
            return
    pat = re.compile(
        r"const getWorkspacePackages = \(\): WorkspacePackage\[\] => \{.*?\n\};", re.S)
    if not pat.search(src):
        sys.exit("patch1: could not find getWorkspacePackages function")
    open(P1_PATH, "w").write(pat.sub(P1_NEW.rstrip("\n"), src, count=1))
    print("patch1: applied")


def patch2():
    src = open(P2_PATH).read()
    if "600000" in src:
        print("patch2: already applied")
        return
    if P2_OLD not in src:
        sys.exit("patch2: could not find 120000 timeout line")
    open(P2_PATH, "w").write(src.replace(P2_OLD, P2_NEW, 1))
    print("patch2: applied")


patch1()
patch2()
print("done")
