// https://medium.com/eclipse-che-blog/coding-my-mock-openid-connect-server-in-go-on-eclipse-che-c096d2a8a314
// https://github.com/sbose78/mock-oauth/blob/master/main.go

package main

import (
	"flag"
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"net/url"
	"os"
)

var (
	message string
	address string
	code    []string
)

func init() {
	flag.StringVar(&address, "address", "0.0.0.0:8080", "address/port to listen on")
}
func main() {
	flag.Parse()
	http.HandleFunc("/auth", handleAuth)
	http.HandleFunc("/token", handleToken)
	http.HandleFunc("/userinfo", handleUserInfo)
	http.HandleFunc("/review", handleReview)
	log.Printf("listening on %s...", address)
	log.Fatal(http.ListenAndServe(address, nil))
}

func handleAuth(w http.ResponseWriter, r *http.Request) {

	whereToRedirect := r.URL.Query().Get("redirect_uri")
	if whereToRedirect == "" {
		whereToRedirect = "http://example.org?no=1234"
	}
	redirectURL, _ := url.Parse(whereToRedirect)
	params := redirectURL.Query()
	params.Set("state", r.URL.Query().Get("state"))

	generatedCode := fmt.Sprintf("%d", rand.Int())
	code = append(code, generatedCode)
	params.Set("code", generatedCode)

	redirectURL.RawQuery = params.Encode()

	if r.Method == "POST" {
		w.Header().Set("Location", redirectURL.String())
		w.WriteHeader(http.StatusTemporaryRedirect)
	} else {
		tmplt := template.Must(template.New("login html").Parse(`
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>oauth-server</title>
</head>
<body>
<ul>
<li><a href="" role="link" name="adm-auth">adm-auth</a></li>
</ul>
<form action="{{ .Query }}" method="post">
<input type="text" name="username" placeholder="kube-admin" />
<input type="password" name="password" placeholder="" />
<input type="submit" value="Login">
</form>
</body>
</html>
`))
		if err := tmplt.Execute(w, struct {
			Query string
		}{
			Query: r.URL.String(),
		}); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
	}
}

func handleToken(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	exchangeCode := r.FormValue("code")
	if !codeValid(exchangeCode) {
		w.WriteHeader(http.StatusUnauthorized)
	} else {
		invalidateCode(r.URL.Query().Get("code"))
		// https://github.com/openshift/oauth-proxy/blob/3d12ccbee45c5d4bcea8c232867df58a60c4382b/providers/openshift/provider.go#L578C29-L578C41
		// kubectl create serviceaccount -n oauth-server admin-user
		// kubectl create clusterrolebinding -n oauth-server admin-user --clusterrole cluster-admin --serviceaccount=oauth-server:admin-user
		// kubectl -n oauth-server create token admin-user
		_, err := w.Write([]byte("{\"token\":\"a34a5f6\",\"access_token\":\"eyJhbGciOiJSUzI1NiIsImtpZCI6IkhMa3ExTEp1aEdRQlZRQnFsamtSbzNwOEhFMlFsbDRfNTFXMmlXSWd6cjQifQ.eyJhdWQiOlsiaHR0cHM6Ly9rdWJlcm5ldGVzLmRlZmF1bHQuc3ZjLmNsdXN0ZXIubG9jYWwiXSwiZXhwIjoxNzQzNzk0ODE5LCJpYXQiOjE3NDM3OTEyMTksImlzcyI6Imh0dHBzOi8va3ViZXJuZXRlcy5kZWZhdWx0LnN2Yy5jbHVzdGVyLmxvY2FsIiwianRpIjoiODc5Y2ZkNTctMWQ4Yi00MzkxLWE1YjYtNmYzODgxNTJjZjFiIiwia3ViZXJuZXRlcy5pbyI6eyJuYW1lc3BhY2UiOiJvYXV0aC1zZXJ2ZXIiLCJzZXJ2aWNlYWNjb3VudCI6eyJuYW1lIjoiYWRtaW4tdXNlciIsInVpZCI6IjExMzk3N2FmLWY2YTAtNDY3Mi05MTU5LTE2MTg1MjY1Njk5ZSJ9fSwibmJmIjoxNzQzNzkxMjE5LCJzdWIiOiJzeXN0ZW06c2VydmljZWFjY291bnQ6b2F1dGgtc2VydmVyOmFkbWluLXVzZXIifQ.gwmS9PMM8dHyWK0_qf82uiGhAulvRc3MiYe43A-KUd7RPstk_91HrQLiXa6buHuy-PCindDY4S14vFe9obkFGlInA61t_dCneO2AkDjcLk136ZzYyZCzmGBVmfpf2AhCv4rkurrMzXDuYBoSDVPAoWvRjGykjjep9zyl8_xUQ42xsyjXdJMyfzyHBkkO8FrKZAznzU1KnjS8TbR1MdEq-KCZDLGde2qBIEXBOxNwLDqxGHXIKZksRUvqvJIUpiijXlXv4eB8mRUhvGCRoKwtbMC9myCv0XuJynLqkOFFV-foWQZPIvTt-FXwJdYna3NSbt1YnKH-5XttP-amcTXxtQ\"}"))
		if err != nil {
			panic(err)
		}
	}
}

// https://github.com/openshift/oauth-proxy/blob/3d12ccbee45c5d4bcea8c232867df58a60c4382b/providers/openshift/provider.go#L477
// defaults.ValidateURL = getKubeAPIURLWithPath("/apis/user.openshift.io/v1/users/~")
func handleUserInfo(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	// Let the mock return whatever username you wish to
	username := os.Getenv("username")
	if username == "" {
		username = "johndoe@gmail.com"
	}
	_, err := w.Write([]byte(fmt.Sprintf("{\"metadata\":{\"name\":\"kube-admin\",\"email\":\"a@a.com\",\"preferred_username\":\"%s\",\"sub\":\"xxx62ccaea02\"}}", username)))
	if err != nil {
		panic(err)
	}
}

// https://github.com/openshift/oauth-proxy/blob/master/providers/openshift/provider.go#L517C29-L517C36
// reviewURL = getKubeAPIURLWithPath("/apis/authorization.openshift.io/v1/subjectaccessreviews")
func handleReview(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_, err := w.Write([]byte("{\"allowed\":true}"))
	if err != nil {
		panic(err)
	}
}

func codeValid(codeInReq string) bool {
	for _, v := range code {
		fmt.Println("found", v, "looking for", codeInReq)
		if v == codeInReq {
			return true
		}
	}
	return false
}

func invalidateCode(codeInReq string) {
	// not thread-safe
	var newListOfValidCodes []string
	for _, v := range code {
		if v != codeInReq {
			newListOfValidCodes = append(newListOfValidCodes, v)
		}
	}
	code = newListOfValidCodes
}
