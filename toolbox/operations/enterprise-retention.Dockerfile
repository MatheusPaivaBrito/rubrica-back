FROM docker:cli AS dockercli
FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends restic bash ca-certificates util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir 'httpx==0.28.1'
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dockercli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose
ENV PYTHONDONTWRITEBYTECODE=1
# Repository/config/secrets are explicit read-only mounts; archives alone are writable.
