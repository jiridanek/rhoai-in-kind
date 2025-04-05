/*
Copyright 2024 The Cozystack Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package groups

import (
	"context"
	"fmt"
	userv1 "github.com/openshift/api/user/v1"
	metainternalversion "k8s.io/apimachinery/pkg/apis/meta/internalversion"
	restclient "k8s.io/client-go/rest"
	"net/http"
	"strings"
	//"sync"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	//fields "k8s.io/apimachinery/pkg/fields"
	//labels "k8s.io/apimachinery/pkg/labels"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/util/duration"
	"k8s.io/apiserver/pkg/endpoints/request"
	"k8s.io/apiserver/pkg/registry/rest"
	"k8s.io/client-go/dynamic"
	"k8s.io/klog/v2"
	//corev1 "k8s.io/api/core/v1"
	//"github.com/aenix-io/cozystack/pkg/config"
	// Importing API errors package to construct appropriate error responses
	//apierrors "k8s.io/apimachinery/pkg/api/errors"
)

// Ensure REST implements necessary interfaces
var (
	_ rest.Getter = &REST{}
	//_ rest.Lister          = &REST{}
	_ rest.Updater         = &REST{}
	_ rest.Creater         = &REST{}
	_ rest.GracefulDeleter = &REST{}
	//_ rest.Watcher         = &REST{}
	_ rest.Patcher = &REST{}
)

// Define constants for label and annotation prefixes
const (
	LabelPrefix      = "apps.cozystack.io-"
	AnnotationPrefix = "apps.cozystack.io-"
)

// Define the GroupVersionResource for HelmRelease
var helmReleaseGVR = schema.GroupVersionResource{
	Group:    "helm.toolkit.fluxcd.io",
	Version:  "v2",
	Resource: "helmreleases",
}

// REST implements the RESTStorage interface for Application resources
type REST struct {
	dynamicClient dynamic.Interface
	gvr           schema.GroupVersionResource
	gvk           schema.GroupVersionKind
	kindName      string
	client        *dynamic.DynamicClient
}

// NewREST creates a new REST storage for Application with specific configuration
func NewREST(config *restclient.Config) *REST {
	dynamicClient, err := dynamic.NewForConfig(config)
	if err != nil {
		panic(fmt.Errorf("unable to create dynamic client: %v", err))
	}
	return &REST{
		client: dynamicClient,
		gvr: schema.GroupVersionResource{
			Group:    userv1.GroupName,
			Version:  "v1",
			Resource: "Groups",
		},
		gvk: schema.GroupVersion{
			Group:   userv1.GroupName,
			Version: "v1",
		}.WithKind("Group"),
		kindName: "Group",
	}
}

// NamespaceScoped indicates whether the resource is namespaced
func (r *REST) NamespaceScoped() bool {
	return false
}

// GetSingularName returns the singular name of the resource
func (r *REST) GetSingularName() string {
	return r.gvr.Resource
}

// Create handles the creation of a new Application by converting it to a HelmRelease
func (r *REST) Create(ctx context.Context, obj runtime.Object, createValidation rest.ValidateObjectFunc, options *metav1.CreateOptions) (runtime.Object, error) {
	return nil, fmt.Errorf("no create, bro")
}

// Get retrieves an Application by converting the corresponding HelmRelease
func (r *REST) Get(ctx context.Context, name string, options *metav1.GetOptions) (runtime.Object, error) {
	//namespace, err := r.getNamespace(ctx)
	//if err != nil {
	//	klog.Errorf("Failed to get namespace: %v", err)
	//	return nil, err
	//}

	klog.V(6).Infof("Attempting to retrieve resource %s of type %s in namespace %s", name, r.gvr.Resource, "no such thing")

	// Convert HelmRelease to Application
	convertedApp := userv1.Group{
		TypeMeta: metav1.TypeMeta{
			Kind:       "Group",
			APIVersion: "user.openshift.io/v1",
		},
		ObjectMeta: metav1.ObjectMeta{
			Name: "admin-user",
		},
		//Identities: []string{"htpasswd-cluster-admin:htpasswd-cluster-admin-user"},
		//Groups:     []string{"dedicated-admins", "system:authenticated", "system:authenticated:oauth"},
	}

	// Convert to unstructured format
	unstructuredApp, err := runtime.DefaultUnstructuredConverter.ToUnstructured(&convertedApp)
	if err != nil {
		klog.Errorf("Failed to convert Application to unstructured for resource %s: %v", name, err)
		return nil, fmt.Errorf("failed to convert Application to unstructured: %v", err)
	}

	// Explicitly set apiVersion and kind in unstructured object
	unstructuredApp["apiVersion"] = convertedApp.TypeMeta.APIVersion
	unstructuredApp["kind"] = convertedApp.TypeMeta.Kind

	klog.V(6).Infof("Successfully retrieved and converted resource %s of kind %s to unstructured", name, r.gvr.Resource)
	return &unstructured.Unstructured{Object: unstructuredApp}, nil
}

// List retrieves a list of Applications by converting HelmReleases
func (r *REST) List(ctx context.Context, options *metainternalversion.ListOptions) (runtime.Object, error) {
	// we'll say we have no groups defined
	groupList := &userv1.GroupList{}
	return groupList, nil
}

// Update updates an existing Application by converting it to a HelmRelease
func (r *REST) Update(ctx context.Context, name string, objInfo rest.UpdatedObjectInfo, createValidation rest.ValidateObjectFunc, updateValidation rest.ValidateObjectUpdateFunc, forceAllowCreate bool, options *metav1.UpdateOptions) (runtime.Object, bool, error) {
	return nil, false, fmt.Errorf("no update %s, bro", name)
}

// Delete removes an Application by deleting the corresponding HelmRelease
func (r *REST) Delete(ctx context.Context, name string, deleteValidation rest.ValidateObjectFunc, options *metav1.DeleteOptions) (runtime.Object, bool, error) {
	return nil, false, fmt.Errorf("no delete, bro")
}

//// Watch sets up a watch on HelmReleases, filters them based on sourceRef and prefix, and converts events to Applications
//func (r *REST) Watch(ctx context.Context, options *metainternalversion.ListOptions) (watch.Interface, error) {
//	return nil, fmt.Errorf("no watch, bro %+v", options)
//}

// getNamespace extracts the namespace from the context
func (r *REST) getNamespace(ctx context.Context) (string, error) {
	namespace, ok := request.NamespaceFrom(ctx)
	if !ok {
		err := fmt.Errorf("namespace not found in context")
		klog.Errorf(err.Error())
		return "", err
	}
	return namespace, nil
}

// buildLabelSelector constructs a label selector string from a map of labels
func buildLabelSelector(labels map[string]string) string {
	var selectors []string
	for k, v := range labels {
		selectors = append(selectors, fmt.Sprintf("%s=%s", k, v))
	}
	return strings.Join(selectors, ",")
}

// mergeMaps combines two maps of labels or annotations
func mergeMaps(a, b map[string]string) map[string]string {
	if a == nil && b == nil {
		return nil
	}
	if a == nil {
		return b
	}
	if b == nil {
		return a
	}
	merged := make(map[string]string, len(a)+len(b))
	for k, v := range a {
		merged[k] = v
	}
	for k, v := range b {
		merged[k] = v
	}
	return merged
}

// addPrefixedMap adds the predefined prefix to the keys of a map
func addPrefixedMap(original map[string]string, prefix string) map[string]string {
	if original == nil {
		return nil
	}
	processed := make(map[string]string, len(original))
	for k, v := range original {
		processed[prefix+k] = v
	}
	return processed
}

// filterPrefixedMap filters a map by the predefined prefix and removes the prefix from the keys
func filterPrefixedMap(original map[string]string, prefix string) map[string]string {
	if original == nil {
		return nil
	}
	processed := make(map[string]string)
	for k, v := range original {
		if strings.HasPrefix(k, prefix) {
			newKey := strings.TrimPrefix(k, prefix)
			processed[newKey] = v
		}
	}
	return processed
}

// computeAge calculates the age of the object based on CreationTimestamp and current time
func computeAge(creationTime, currentTime time.Time) string {
	ageDuration := currentTime.Sub(creationTime)
	return duration.HumanDuration(ageDuration)
}

// getReadyStatus returns the ready status based on conditions
func getReadyStatus(conditions []metav1.Condition) string {
	for _, condition := range conditions {
		if condition.Type == "Ready" {
			switch condition.Status {
			case metav1.ConditionTrue:
				return "True"
			case metav1.ConditionFalse:
				return "False"
			default:
				return "Unknown"
			}
		}
	}
	return "Unknown"
}

// ConvertToTable implements the TableConvertor interface for displaying resources in a table format
func (r *REST) ConvertToTable(ctx context.Context, object runtime.Object, tableOptions runtime.Object) (*metav1.Table, error) {
	klog.V(6).Infof("ConvertToTable: received object of type %T", object)

	var table metav1.Table

	switch obj := object.(type) {
	case *userv1.GroupList:
		table = r.buildTableFromApplications(obj.Items)
		table.ListMeta.ResourceVersion = obj.ListMeta.ResourceVersion
	case *userv1.Group:
		table = r.buildTableFromApplication(*obj)
		table.ListMeta.ResourceVersion = obj.GetResourceVersion()
	case *unstructured.Unstructured:
		var app userv1.Group
		err := runtime.DefaultUnstructuredConverter.FromUnstructured(obj.UnstructuredContent(), &app)
		if err != nil {
			klog.Errorf("Failed to convert Unstructured to Application: %v", err)
			return nil, fmt.Errorf("failed to convert Unstructured to Application: %v", err)
		}
		table = r.buildTableFromApplication(app)
		table.ListMeta.ResourceVersion = obj.GetResourceVersion()
	default:
		resource := schema.GroupResource{}
		if info, ok := request.RequestInfoFrom(ctx); ok {
			resource = schema.GroupResource{Group: info.APIGroup, Resource: info.Resource}
		}
		return nil, errNotAcceptable{
			resource: resource,
			message:  "object does not implement the Object interfaces",
		}
	}

	// Handle table options
	if opt, ok := tableOptions.(*metav1.TableOptions); ok && opt != nil && opt.NoHeaders {
		table.ColumnDefinitions = nil
	}

	table.TypeMeta = metav1.TypeMeta{
		APIVersion: "meta.k8s.io/v1",
		Kind:       "Table",
	}

	klog.V(6).Infof("ConvertToTable: returning table with %d rows", len(table.Rows))

	return &table, nil
}

// buildTableFromApplications constructs a table from a list of Applications
func (r *REST) buildTableFromApplications(apps []userv1.Group) metav1.Table {
	table := metav1.Table{
		ColumnDefinitions: []metav1.TableColumnDefinition{
			{Name: "NAME", Type: "string", Description: "Name of the Application", Priority: 0},
			{Name: "READY", Type: "string", Description: "Ready status of the Application", Priority: 0},
			{Name: "AGE", Type: "string", Description: "Age of the Application", Priority: 0},
			{Name: "VERSION", Type: "string", Description: "Version of the Application", Priority: 0},
		},
		Rows: make([]metav1.TableRow, 0, len(apps)),
	}
	now := time.Now()

	for _, app := range apps {
		row := metav1.TableRow{
			Cells:  []interface{}{app.GetName(), getReadyStatus([]metav1.Condition{}), computeAge(app.GetCreationTimestamp().Time, now), "v1"},
			Object: runtime.RawExtension{Object: &app},
		}
		table.Rows = append(table.Rows, row)
	}

	return table
}

// buildTableFromApplication constructs a table from a single Application
func (r *REST) buildTableFromApplication(app userv1.Group) metav1.Table {
	table := metav1.Table{
		ColumnDefinitions: []metav1.TableColumnDefinition{
			{Name: "NAME", Type: "string", Description: "Name of the Application", Priority: 0},
			{Name: "READY", Type: "string", Description: "Ready status of the Application", Priority: 0},
			{Name: "AGE", Type: "string", Description: "Age of the Application", Priority: 0},
			{Name: "VERSION", Type: "string", Description: "Version of the Application", Priority: 0},
		},
		Rows: []metav1.TableRow{},
	}
	now := time.Now()

	row := metav1.TableRow{
		Cells:  []interface{}{app.GetName(), getReadyStatus([]metav1.Condition{}), computeAge(app.GetCreationTimestamp().Time, now), "v1"},
		Object: runtime.RawExtension{Object: &app},
	}
	table.Rows = append(table.Rows, row)

	return table
}

// Destroy releases resources associated with REST
func (r *REST) Destroy() {
	// No additional actions needed to release resources.
}

// New creates a new instance of Application
func (r *REST) New() runtime.Object {
	return &userv1.Group{}
}

// NewList returns an empty list of Application objects
func (r *REST) NewList() runtime.Object {
	return &userv1.GroupList{}
}

// Kind returns the resource kind used for API discovery
func (r *REST) Kind() string {
	return r.gvk.Kind
}

// GroupVersionKind returns the GroupVersionKind for REST
func (r *REST) GroupVersionKind(schema.GroupVersion) schema.GroupVersionKind {
	return r.gvk
}

// errNotAcceptable indicates that the resource does not support conversion to Table
type errNotAcceptable struct {
	resource schema.GroupResource
	message  string
}

func (e errNotAcceptable) Error() string {
	return e.message
}

func (e errNotAcceptable) Status() metav1.Status {
	return metav1.Status{
		Status:  metav1.StatusFailure,
		Code:    http.StatusNotAcceptable,
		Reason:  metav1.StatusReason("NotAcceptable"),
		Message: e.Error(),
	}
}
