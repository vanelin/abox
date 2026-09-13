FROM mcr.microsoft.com/devcontainers/universal:6-noble

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    asciinema build-essential cmake jq libcurl4-openssl-dev shellcheck unzip \
    && rm -rf /var/lib/apt/lists/*

# Match the repository pin even when no dotfiles/version manager is installed.
COPY .opentofu-version /tmp/abox-opentofu-version
RUN set -eu; \
    version="$(cat /tmp/abox-opentofu-version)"; \
    arch="$(dpkg --print-architecture)"; \
    archive="tofu_${version}_linux_${arch}.zip"; \
    base="https://github.com/opentofu/opentofu/releases/download/v${version}"; \
    mkdir /tmp/abox-tofu; cd /tmp/abox-tofu; \
    curl -fsSLO "${base}/${archive}"; \
    curl -fsSLO "${base}/tofu_${version}_SHA256SUMS"; \
    grep " ${archive}\$" "tofu_${version}_SHA256SUMS" | sha256sum -c -; \
    unzip -q "$archive" tofu; \
    install -m 0755 tofu /usr/local/bin/tofu; \
    rm -rf /tmp/abox-tofu /tmp/abox-opentofu-version

ARG FLUX_VERSION=2.9.5
RUN set -eu; \
    arch="$(dpkg --print-architecture)"; \
    archive="flux_${FLUX_VERSION}_linux_${arch}.tar.gz"; \
    base="https://github.com/fluxcd/flux2/releases/download/v${FLUX_VERSION}"; \
    mkdir /tmp/abox-flux; cd /tmp/abox-flux; \
    curl -fsSLO "${base}/${archive}"; \
    curl -fsSLO "${base}/flux_${FLUX_VERSION}_checksums.txt"; \
    grep " ${archive}\$" "flux_${FLUX_VERSION}_checksums.txt" | sha256sum -c -; \
    tar -xzf "$archive" flux; \
    install -m 0755 flux /usr/local/bin/flux; \
    rm -rf /tmp/abox-flux

USER codespace
