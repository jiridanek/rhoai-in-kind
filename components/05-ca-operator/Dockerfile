# podman build -t quay.io/jdanek/origin-service-ca-operator

FROM quay.io/openshift/origin-service-ca-operator@sha256:1441889d1231e30d702c97f0d713af274284eaf4c0b8dca2a618cd6b55559282

# workaround for https://github.com/openshift/service-ca-operator/issues/237
USER 1001:0
