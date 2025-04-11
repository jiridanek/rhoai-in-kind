## Kubernetes Extension API Server

This component implements an APIService that exposes the following OpenShift resources otherwise unavailable on Kubernetes:

* User
* Project
* ProjectRequest

These resources are needed for the ODH Dashboard to function.
It is not possible to provide them through CRDs (CustomResourceDefinition CRs) because they require a special implementation.

### User

Namely, there has to be an instance of User named `~` (tilde) that returns information about the currently logged user.
This is similar to the `SelfSubjectAccess` review in Kubernetes.
This is not possible with CRDs because a resource created through CRDs may not be named `~`.

Here is what has to work with respect to the `Users` resource:

```shell
$ oc get --raw '/apis/user.openshift.io/v1/users/~'
{
	"kind":"User",
	"apiVersion":"user.openshift.io/v1",
	"metadata":{
		"name":"htpasswd-cluster-admin-user",
		"uid":"762e9fc7-714a-4194-8d43-89c04073baf3",
		"resourceVersion":"9959783",
		"creationTimestamp":"2024-10-16T08:46:54Z"
	},
	"identities":["htpasswd-cluster-admin:htpasswd-cluster-admin-user"],
	"groups":["dedicated-admins","system:authenticated","system:authenticated:oauth"]
}
```

### Project

Next, the Project resource needs to be an alias for the Namespace resource.
Every Namespace resource has to have a corresponding Project, and vice versa.

The `ProjectRequest` resource is a special resource that is used to create new Projects in OpenShift and oc new-project requires it to exist.

The above constraints suggest that writing a custom controller to keep Project instances in sync should be possible, but in practice this is not the case.
The `oc` client will error out and crash if a ProjectRequest resource defines a ProjectRequestList type, and there is no way to not define this with CRDs.

```commandline
error: no kind "ProjectRequestList" is registered for version "project.openshift.io/v1" in scheme "github.com/openshift/client-go/project/clientset/versioned/scheme/register.go:14"
```

## Implementation guidance

There is a very helpful blog from Cozystack authors, that provides comprehensive background on Extension API Servers.
It maps their use in various projects (Kubevirt, Cozystack) and describes the Cozystack implemention in detail.
https://kubernetes.io/blog/2024/11/21/dynamic-kubernetes-api-server-for-cozystack/

(Also available at https://blog.aenix.io/how-we-built-a-dynamic-kubernetes-api-server-for-the-api-aggregation-layer-in-cozystack-15709a183c86)

In addition, there is naturally something in the Kubernetes documentation.
https://kubernetes.io/docs/concepts/extend-kubernetes/api-extension/apiserver-aggregation/

People tend to use https://github.com/kubernetes/sample-apiserver/blob/master/README.md as starter project,
there is also some builder thing but that is mostly abandoned https://github.com/kubernetes-sigs/apiserver-builder-alpha.

Here's an example APIService CR

https://kubernetes.io/docs/tasks/extend-kubernetes/configure-aggregation-layer/#register-apiservice-objects
```yaml
apiVersion: apiregistration.k8s.io/v1
kind: APIService
metadata:
  name: fake-users-service
spec:
  group: <API group name this extension apiserver hosts>
  version: <API version this extension apiserver hosts>
  groupPriorityMinimum: <priority this APIService for this group, see API documentation>
  versionPriority: <prioritizes ordering of this version within a group, see API documentation>
  service:
    namespace: fake-openshift-compatibility
    name: my-service-name
    port: 1234
  caBundle: <pem encoded ca cert that signs the server cert used by the webhook>
```

Documentation says that Extension API servers have to be enabled in the kube-apiserver.
Thankfully, KinD already has the apiserver flags set by default:
* https://kubernetes.io/docs/tasks/extend-kubernetes/configure-aggregation-layer/#kubernetes-apiserver-client-authentication
* https://kubernetes.io/docs/tasks/extend-kubernetes/configure-aggregation-layer/#enable-kubernetes-apiserver-flags

```shell
podman exec kind-control-plane ps -ef | grep apiserver
root         478     254  8 Mar03 ?        06:16:02 kube-apiserver
   --advertise-address=10.89.0.2
   --allow-privileged=true
   --authorization-mode=Node,RBAC
   --client-ca-file=/etc/kubernetes/pki/ca.crt
   --enable-admission-plugins=NodeRestriction
   --enable-bootstrap-token-auth=true
   --etcd-cafile=/etc/kubernetes/pki/etcd/ca.crt
   --etcd-certfile=/etc/kubernetes/pki/apiserver-etcd-client.crt
   --etcd-keyfile=/etc/kubernetes/pki/apiserver-etcd-client.key
   --etcd-servers=https://127.0.0.1:2379
   --kubelet-client-certificate=/etc/kubernetes/pki/apiserver-kubelet-client.crt
   --kubelet-client-key=/etc/kubernetes/pki/apiserver-kubelet-client.key
   --kubelet-preferred-address-types=InternalIP,ExternalIP,Hostname
   --proxy-client-cert-file=/etc/kubernetes/pki/front-proxy-client.crt
   --proxy-client-key-file=/etc/kubernetes/pki/front-proxy-client.key
   --requestheader-allowed-names=front-proxy-client
   --requestheader-client-ca-file=/etc/kubernetes/pki/front-proxy-ca.crt
   --requestheader-extra-headers-prefix=X-Remote-Extra-
   --requestheader-group-headers=X-Remote-Group
   --requestheader-username-headers=X-Remote-User
   --runtime-config=
   --secure-port=6443
   --service-account-issuer=https://kubernetes.default.svc.cluster.local
   --service-account-key-file=/etc/kubernetes/pki/sa.pub
   --service-account-signing-key-file=/etc/kubernetes/pki/sa.key
   --service-cluster-ip-range=10.96.0.0/16
   --tls-cert-file=/etc/kubernetes/pki/apiserver.crt
   --tls-private-key-file=/etc/kubernetes/pki/apiserver.key
```

Code in Kubevirt project can be referenced

* https://github.com/kubevirt/vm-console-proxy/blob/71cec9d52b2bebabd6b238d7683422773ab69eab/manifests/api_service.yaml#L4
* https://github.com/kubevirt/vm-console-proxy/blob/71cec9d52b2bebabd6b238d7683422773ab69eab/README.md?plain=1#L20
* `kubectl apply -f "https://github.com/kubevirt/vm-console-proxy/releases/latest/download/vm-console-proxy.yaml"`
