#!/usr/bin/env bash
set -e

kubectl patch -n redhat-ods-applications odhdashboardconfig odh-dashboard-config -n redhat-ods-applications --type=json -p '[
  {
    "op": "replace",
    "path": "/spec/notebookSizes/0/resources/requests/cpu",
    "value": "1m"
  },
  {
    "op": "replace",
    "path": "/spec/notebookSizes/0/resources/requests/memory",
    "value": "8Mi"
  }
]'
