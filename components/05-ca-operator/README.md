The ca-operator is important especially for odh-pipelines component.

```commandline
baf ds-pipeline-ui-sample-6c699f4794-kqcgr oauth-proxy E0410 10:13:11.852435       1 reflector.go:148] github.com/openshift/oauth-proxy/providers/openshift/provider.go:354: Failed to watch *v1.ConfigMap: failed to list *v1.ConfigMap: configmaps "oauth-serving-cert" is forbidden: User "system:serviceaccount:baf:ds-pipeline-ui-sample" cannot list resource "configmaps" in API group "" in the namespace "openshift-config-managed"
```

Thankfully, the OKD version of the operator is working just fine on KinD, assuming we workaround issue

* https://github.com/openshift/service-ca-operator/issues/237

Alternative way (not using custom Dockerfile) may be achieved with Kyverno.
