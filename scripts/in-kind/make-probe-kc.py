import yaml

cert = open("/tmp/kf3x/probe-ca.b64").read().strip()
token = None
for line in open("/tmp/kf3x/probe-token.env"):
    if line.startswith("TOKEN="):
        token = line.strip()[6:]
assert token and cert, (len(token or ""), len(cert))

server = "https://127.0.0.1:6443"
user = "system:serviceaccount:oauth-server:htpasswd-cluster-admin-user"
ctx = "default/127-0-0-1:6443/" + user

kc = {
    "apiVersion": "v1",
    "kind": "Config",
    "clusters": [{
        "name": "default",
        "cluster": {"certificate-authority-data": cert, "server": server},
    }],
    "users": [{
        "name": user,
        "user": {"token": token},
    }],
    "contexts": [{
        "name": ctx,
        "context": {"cluster": "default", "user": user},
    }],
    "current-context": ctx,
}
with open("/tmp/rhoai-odh3x/.kubeconfig-probe", "w") as f:
    yaml.safe_dump(kc, f, default_flow_style=False, sort_keys=False)
print("written", ctx)
