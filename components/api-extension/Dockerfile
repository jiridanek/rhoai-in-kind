# Copyright 2017 The Kubernetes Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# podman build -t quay.io/jdanek/api-extension:latest -f components/api-extension/Dockerfile components/api-extension/
# podman push quay.io/jdanek/api-extension:latest
# kind load docker-image quay.io/jdanek/api-extension:latest

FROM docker.io/library/golang:1.24 as builder
COPY go.mod go.sum ./
RUN go mod download
COPY . ./
RUN CGO_ENABLED=0 GOOS=linux go build -o /api-extension

FROM fedora
COPY --from=builder /api-extension /
RUN mkdir apiserver.local.config
RUN chown 1001:0 apiserver.local.config

USER 1001:0

ENTRYPOINT ["/api-extension"]
