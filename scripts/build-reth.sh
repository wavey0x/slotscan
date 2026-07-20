#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "usage: scripts/build-reth.sh [output-directory]" >&2
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
[[ $# -le 1 ]] || { usage; exit 2; }

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
crate="$root/reth-slotscan"
output_dir="${1:-$root/dist}"

[[ "$(uname -s)" == "Linux" && "$(uname -m)" == "x86_64" ]] || {
  echo "release artifacts must be built natively on Linux x86_64" >&2
  exit 1
}
[[ -z "$(git -C "$root" status --short)" ]] || {
  echo "release builds require a clean worktree" >&2
  exit 1
}

commit="$(git -C "$root" rev-parse HEAD)"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo "could not resolve source commit" >&2; exit 1; }
version="$(sed -nE 's/^version = "([^"]+)"$/\1/p' "$crate/Cargo.toml" | head -n1)"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+-slotscan\.[0-9]+$ ]] || {
  echo "invalid SlotScan package version: ${version:-missing}" >&2
  exit 1
}

cargo fmt --manifest-path "$crate/Cargo.toml" --check
cargo check --locked --manifest-path "$crate/Cargo.toml" --features production
cargo test --locked --manifest-path "$crate/Cargo.toml" --features production
cargo clippy --locked --manifest-path "$crate/Cargo.toml" \
  --all-targets --features production -- -D warnings
SLOTSCAN_BUILD_COMMIT="$commit" \
  cargo build --locked --manifest-path "$crate/Cargo.toml" \
  --profile maxperf --features production

binary="$crate/target/maxperf/reth-slotscan"
version_output="$("$binary" --version)"
grep -Fxq "SlotScan Reth Version: ${version}" <<<"$version_output"
grep -Fxq "SlotScan Commit: ${commit}" <<<"$version_output"
grep -Fxq "Build Profile: maxperf" <<<"$version_output"
for feature in asm_keccak jemalloc keccak_cache_global min_trace_logs otlp otlp_logs; do
  grep -Fq "$feature" <<<"$version_output"
done

"$root/scripts/smoke-reth-slotscan.sh" "$binary"

mkdir -p "$output_dir"
archive="$output_dir/reth-v${version}-x86_64-unknown-linux-gnu.tar.gz"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
install -m 0755 "$binary" "$staging/reth"
tar -C "$staging" -czf "$archive" reth
[[ "$(tar -tzf "$archive")" == "reth" ]] || {
  echo "release archive must contain only a top-level reth executable" >&2
  exit 1
}
sha256sum "$archive"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  printf 'archive=%s\n' "$archive" >>"$GITHUB_OUTPUT"
fi
echo "$archive"
