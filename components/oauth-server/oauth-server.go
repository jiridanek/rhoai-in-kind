// https://medium.com/eclipse-che-blog/coding-my-mock-openid-connect-server-in-go-on-eclipse-che-c096d2a8a314
// https://github.com/sbose78/mock-oauth/blob/master/main.go

package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"html/template"
	"k8s.io/client-go/rest"
	"k8s.io/utils/ptr"
	"log"
	"math/rand"
	"net/http"
	"net/url"
	"os"
	"time"

	authenticationv1 "k8s.io/api/authentication/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
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
	log.Printf("%s %s %s", r.RemoteAddr, r.Method, r.URL)
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

type OauthTokenResponse struct {
	Token       string `json:"token"`
	AccessToken string `json:"access_token"`
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
		// kubectl -n oauth-server create token admin-user --duration=168h
		config, err := rest.InClusterConfig()
		if err != nil {
			panic(err.Error())
		}
		clientset, err := kubernetes.NewForConfig(config)
		if err != nil {
			panic(err.Error())
		}
		tokenRequest := &authenticationv1.TokenRequest{
			Spec: authenticationv1.TokenRequestSpec{
				ExpirationSeconds: ptr.To(int64(168 * time.Hour / time.Second)), // 168 hours in seconds
			},
		}
		token, err := clientset.CoreV1().ServiceAccounts("oauth-server").CreateToken(context.TODO(), "admin-user", tokenRequest, metav1.CreateOptions{})
		if err != nil {
			panic(err.Error())
		}
		fmt.Printf("Token expires At: %s\n", token.Status.ExpirationTimestamp.Format(time.RFC3339))
		tokenResp := OauthTokenResponse{
			Token:       "a34a5f6",
			AccessToken: token.Status.Token,
		}
		jsonResponse, err := json.Marshal(tokenResp)
		if err != nil {
			http.Error(w, "Error encoding JSON response", http.StatusInternalServerError)
			return
		}
		_, err = w.Write(jsonResponse)
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
