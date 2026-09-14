FROM scratch
COPY oauth-proxy-amd64 /usr/bin/oauth-proxy
ENTRYPOINT ["/usr/bin/oauth-proxy"]
