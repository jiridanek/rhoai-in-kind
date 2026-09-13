# Release profiles

A **release profile** is the single source of truth for *everything that differs between ODH/RHOAI
release trains* in this repo. "Which ODH version am I deploying + testing" = *which profile*.

See **docs/odh-2x-vs-3x-organization.md** for the full rationale and why we use profiles instead of
per-version branches or subtrees.

## Files

- `2.25.z.yaml` — the current, known-good 2.x (rhoai-2.25) pins. **This is the default.**
- `3.x.yaml` — a **draft** 3.x profile (values marked `TODO`). Filling this in = Phase P1.

## Adding / bumping a release

1. Copy the nearest profile (e.g. `cp 2.25.z.yaml 3.4.yaml`).
2. Update the component refs + test refs for that train.
3. Where a pin is a *cross-reference* (workbench tag ↔ image tag ↔ prepull digests), update them
   together and re-derive the digests from a fresh run's cluster-logs (the same caution that's
   already in the workflows).

## Schema (fields a profile declares)

All fields below map 1:1 to a pin documented in
`docs/odh-2x-vs-3x-organization.md` §2. A profile that omits a field inherits it from the default
profile (2.25.z).

    # --- component refs (the "which ODH version") -----------------------------------
    name:            2.25.z        # release-train name; also the profile filename
    default:         true          # used when --release is omitted
    workbench_branch:   v1.36.0    # notebooks repo checkout ref  (deploy.py --workbench-branch)
    notebook_image_tag: 2025b-v1.36 # quay.io tag for the workbench/runtime images
    dspo_target_revision: v2.15.1   # data-science-pipelines-operator (03-kf-pipelines)
    dashboard_target_revision: v2.37.1-odh  # odh-dashboard (04-odh-dashboard)
    notebook_controller_ref: v1.10.0-5      # kubeflow notebook controllers (09-kf-notebooks)

    # --- image overrides (per-component) -------------------------------------------
    dspo_image_overrides: { ... }   # IMAGES_MLMDENVOY / IMAGES_OAUTHPROXY / IMAGES_MARIADB
    dashboard_image: quay.io/opendatahub/odh-dashboard:v2.37.1-odh
    dashboard_oauthproxy_images: [ ... ]  # registry.redhat.io -> quay.io/jdanek rewrites

    # --- fake control plane (things that only need to exist) ------------------------
    fake_dsc_version: 2.13.0        # fake DataScienceCluster/CSV version (07-dsc-dsci)
    component_cr_version: 2.22.0    # components.platform.opendatahub.io/v1alpha1 Dashboard
    dsc_management_states: { ... }  # the per-component managementState set
    fake_crds: components/crds      # dir to apply (add/remove CRDs per train as needed)

    # --- tests ----------------------------------------------------------------------
    tests:
      ods_ci_ref: release-2.25            # ods-ci branch/tag
      cypress_dashboard_ref: v2.37.1-odh  # odh-dashboard repo ref for cypress
      opendatahub_tests_ref: 94670b33...  # opendatahub-tests SHA/branch
      test_variables_file: components/ods-ci/test-variables.yml
      prepull_images: [ ... ]             # workbench/runtime image digests to pre-pull

> These files are currently **documentation/scaffolding only** — nothing reads them yet. Wiring
> `deploy.py` + the 3 workflows to consume them is Phase P0 of the plan. They are additive and
> change no behavior.
