FROM mcr.microsoft.com/devcontainers/rust:1-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ncurses-term \
        musl-tools shellcheck \
    && rm -rf /var/lib/apt/lists/*

# SSH login shells do not inherit Docker ENV.
RUN printf '%s\n' \
    'export RUSTUP_HOME=/usr/local/rustup' \
    'export CARGO_HOME=/usr/local/cargo' \
    'export PATH=/usr/local/cargo/bin:$PATH' \
    > /etc/profile.d/rust.sh

USER vscode
# Local builds of the static Linux release binary (CC=musl-gcc).
RUN rustup target add x86_64-unknown-linux-musl
RUN curl -fsSL https://claude.ai/install.sh | bash
RUN curl -fsSL https://herdr.dev/install.sh | sh
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# The sshd feature needs root.
USER root
