#!/usr/bin/env python3
import pathlib
import textwrap
import os
import platform
import subprocess
import sys


def self_signed_issuer():
    # This would create a new CA for each certificate, I don't want that
    # language=YAML
    request = textwrap.dedent(
        '''
        apiVersion: cert-manager.io/v1
        kind: Issuer
        metadata:
          name: self-signed-issuer
          namespace: cert-manager
        spec:
          selfSigned: { }
        '''
    )
    pathlib.Path("self-signed-issuer.yaml").write_text(request)
    sh("kubectl apply -f self-signed-issuer.yaml")

def ca_issuer():
    """
    Verify:
    ❯ openssl s_client -showcerts -connect minio-console.apps.127.0.0.1.sslip.io:443 </dev/null | sed -n '/-----BEGIN/,/-----END/p' > server.crt
    ❯ openssl verify -CAfile /Users/jdanek/IdeaProjects/rhoai-in-kind/ca.crt server.crt
    """
    sh("kubectl delete configmap odh-trusted-ca-bundle --namespace=cert-manager --ignore-not-found")
    sh("kubectl delete secret my-cluster-ca-secret --namespace=cert-manager --ignore-not-found")
    sh("kubectl delete issuer my-cluster-ca-issuer --namespace=cert-manager --ignore-not-found")
    sh("kubectl delete certificate sslip-io-certificate --namespace=cert-manager --ignore-not-found")
    sh("kubectl delete secret sslip-tls-secret --namespace=cert-manager --ignore-not-found")

    # language=YAML
    request = textwrap.dedent(
        '''
        apiVersion: cert-manager.io/v1
        kind: Issuer
        metadata:
          name: my-cluster-ca-issuer
          namespace: cert-manager
        spec:
          ca:
            secretName: my-cluster-ca-secret
        '''
    )
    pathlib.Path("my-cluster-ca-issuer.yaml").write_text(request)
    # Error from server (InternalError): error when creating "my-cluster-ca-issuer.yaml": Internal error occurred: failed calling webhook "webhook.cert-manager.io": failed to call webhook: Post "https://cert-manager-webhook.cert-manager.svc:443/validate?timeout=30s": dial tcp 10.96.78.75:443: connect: connection refused
    sh("timeout 30s bash -c 'while ! kubectl apply -f my-cluster-ca-issuer.yaml; do sleep 1; done'")

    # todo: remove dns name from cacert?
    sh("openssl req -x509 -new -nodes -keyout ca.key -sha256 -days 3650 -out ca.crt -subj '/CN=My Cluster CA' -addext 'subjectAltName = DNS:*.apps.127.0.0.1.sslip.io'")
    sh("kubectl create secret tls my-cluster-ca-secret --cert=ca.crt --key=ca.key --namespace=cert-manager --dry-run=client -o yaml | kubectl apply -f -")

    sh(f"kubectl create configmap odh-trusted-ca-bundle --namespace=cert-manager --from-file=odh-ca-bundle.crt=ca.crt --from-file=ca-bundle.crt={find_ca_bundle_path()} --dry-run=client -o yaml | kubectl apply -f -")

    ## Option 2: Use trust-manager (The Recommended Method) 🚀

    # language=YAML
    request = textwrap.dedent(
        '''
        apiVersion: cert-manager.io/v1
        kind: Certificate
        metadata:
          name: sslip-io-certificate
          namespace: cert-manager
        spec:
          privateKey:
            # message: 'Existing private key is not up to date for spec: [spec.privateKey.algorithm]'
            #algorithm: ECDSA
            #size: 256
            #encoding: PKCS8
            rotationPolicy: Never
          secretName: sslip-tls-secret # The secret where the cert/key will be stored
          commonName: "*.apps.127.0.0.1.sslip.io"
          dnsNames:
            - "*.apps.127.0.0.1.sslip.io"
          issuerRef:
            name: my-cluster-ca-issuer
            kind: Issuer
        '''
    )
    pathlib.Path("sslip-certificate.yaml").write_text(request)
    sh("kubectl apply -f sslip-certificate.yaml")
    sh("kubectl wait --for=condition=Ready certificate/sslip-io-certificate -n cert-manager --timeout=20s")

def main():
    ca_issuer()

def sh(cmd: str, check=True, stdout: bool = False, stderr: bool = False) -> str | None:
    print(f"$ {cmd}")
    p = subprocess.run(
        f"set -Eeuo pipefail; {cmd}",
        shell=True,
        executable="/bin/bash",
        stdout=subprocess.PIPE if stdout else None,
        stderr=subprocess.PIPE if stderr else None
    )
    sys.stdout.flush()
    if check:
        p.check_returncode()
    if stdout:
        return p.stdout.decode('utf-8')
    return None


def find_ca_bundle_path() -> str | None:
    """
    Finds the path to the system CA bundle, portable across Linux and macOS.
    """
    system = platform.system()

    # --- For Linux ---
    if system == "Linux":
        # A list of common, prioritized paths for Linux distributions
        linux_paths = [
            "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu, Arch
            "/etc/pki/tls/certs/ca-bundle.crt",  # Red Hat, Fedora, CentOS
        ]
        for path in linux_paths:
            if os.path.isfile(path):
                return path

    # --- For macOS ---
    elif system == "Darwin":
        # Try system keychain first
        system_bundle = pathlib.Path("macos-native-ca-bundle.pem").resolve().absolute().as_posix()
        sh(
            "security find-certificate -a -p "
            "/System/Library/Keychains/SystemRootCertificates.keychain "
            "> macos-native-ca-bundle.pem"
        )
        if os.path.isfile(system_bundle):
            return system_bundle

        # Fallback to Homebrew OpenSSL if available
        try:
            result = subprocess.run(
                ["brew", "--prefix", "openssl"],
                capture_output=True,
                text=True,
                check=True
            )
            brew_path = os.path.join(result.stdout.strip(), "etc/openssl/cert.pem")
            if os.path.isfile(brew_path):
                return brew_path
        except subprocess.CalledProcessError:
            pass
    # If no path was found, return None
    return None


if __name__ == '__main__':
    main()
