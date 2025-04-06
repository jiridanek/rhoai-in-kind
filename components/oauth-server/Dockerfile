# podman build -t quay.io/jdanek/oauth-server:latest -f components/oauth-server/Dockerfile components/oauth-server/
# podman push quay.io/jdanek/oauth-server:latest
# kind load docker-image quay.io/jdanek/oauth-server:latest

FROM docker.io/library/golang:1.24 as builder
COPY go.mod go.sum ./
RUN go mod download
COPY oauth-server.go ./
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /oauth-server oauth-server.go

FROM scratch
COPY --from=builder /oauth-server oauth-server
ENTRYPOINT ["/oauth-server"]
