#!/usr/bin/env bash
set -Eeuxo pipefail

# Generate a private key
openssl genpkey -algorithm RSA -out nginx.key

# Generate a Certificate Signing Request (CSR)
# Fill in details when prompted - Common Name (CN) could be 'localhost' or '127.0.0.1'
openssl req -new -key nginx.key -out nginx.csr -subj "/CN=localhost"

# Generate the self-signed certificate (valid for 365 days)
openssl x509 -req -days 365 -in nginx.csr -signkey nginx.key -out nginx.crt
