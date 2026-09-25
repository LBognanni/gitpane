#!/bin/sh
# Install gitpane from GitHub Releases:
#   curl -fsSL https://github.com/LBognanni/gitpane/releases/latest/download/install.sh | sh
# GITPANE_VERSION picks a release tag (default: the release this script was
# downloaded from; latest when run from the repository).
# GITPANE_INSTALL_DIR picks the directory (default: ~/.local/bin).
set -eu

main() {
    case "$(uname -s) $(uname -m)" in
        "Linux x86_64") target=x86_64-unknown-linux-musl ;;
        "Linux aarch64" | "Linux arm64") target=aarch64-unknown-linux-musl ;;
        "Darwin x86_64") target=x86_64-apple-darwin ;;
        "Darwin arm64") target=aarch64-apple-darwin ;;
        *) echo "gitpane: unsupported platform: $(uname -sm)" >&2; exit 1 ;;
    esac

    version="${GITPANE_VERSION:-latest}"
    if [ "$version" = latest ]; then
        base=https://github.com/LBognanni/gitpane/releases/latest/download
    else
        base="https://github.com/LBognanni/gitpane/releases/download/$version"
    fi

    dir="${GITPANE_INSTALL_DIR:-$HOME/.local/bin}"
    mkdir -p "$dir"
    # Extract next to the destination so the final mv is an atomic rename,
    # which also works while gitpane is running.
    tmp="$(mktemp -d "$dir/.gitpane.XXXXXX")"
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL -o "$tmp/gitpane.tar.gz" "$base/gitpane-$target.tar.gz"
    tar -xzf "$tmp/gitpane.tar.gz" -C "$tmp"
    mv "$tmp/gitpane" "$dir/gitpane"

    echo "Installed $("$dir/gitpane" --version) to $dir"
    case ":$PATH:" in
        *":$dir:"*) ;;
        *) echo "Add $dir to your PATH to run gitpane." ;;
    esac
}

main "$@"
