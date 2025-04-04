# GOOS=linux go build oauth-server.go
# podman build -f Dockerfile.oauth-server -t oauth-server:latest .
# kind load docker-image localhost/oauth-server:latest
FROM scratch
copy oauth-server /
ENTRYPOINT ["/oauth-server"]
