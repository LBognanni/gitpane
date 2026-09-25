#!/usr/bin/env bash
# Set up SSH access and the shell inside the container. Runs in the worktree.
set -euo pipefail

key=.devcontainer/.ssh/id_ed25519
if [ ! -f "$key" ]; then
  mkdir -p "$(dirname "$key")"
  ssh-keygen -q -t ed25519 -N '' -C gitpane-devcontainer -f "$key"
fi

mkdir -p ~/.ssh
chmod 700 ~/.ssh
cp "$key.pub" ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

if ! grep -q 'gitpane-workspace' ~/.bashrc; then
  echo "[ -n \"\${SSH_CONNECTION:-}\" ] && cd '$PWD' # gitpane-workspace" >> ~/.bashrc
fi

git config --global --add safe.directory '*'

# Docker creates a new cargo registry volume owned by root.
sudo chown vscode:rustlang /usr/local/cargo/registry

# Keep Claude Code's state across rebuilds in the mounted ~/.claude directory.
# A single-file bind mount breaks on atomic rewrites, so symlink instead.
ln -sfn ~/.claude/devcontainer.claude.json ~/.claude.json
