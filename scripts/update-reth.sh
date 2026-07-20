#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "usage: scripts/update-reth.sh vX.Y.Z" >&2
}

[[ $# -eq 1 ]] || { usage; exit 2; }

reth_tag="$1"
[[ "$reth_tag" =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]] || {
  echo "Reth version must be a stable tag such as v2.4.0" >&2
  exit 2
}

reth_version="${reth_tag#v}"
slotscan_version="${reth_version}-slotscan.1"
repo_url="https://github.com/paradigmxyz/reth"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
crate="$root/reth-slotscan"
manifest="$crate/Cargo.toml"
lockfile="$crate/Cargo.lock"
toolchain="$crate/rust-toolchain.toml"

tag_refs="$(git ls-remote --tags "$repo_url" \
  "refs/tags/${reth_tag}" "refs/tags/${reth_tag}^{}")"
reth_commit="$(awk -v ref="refs/tags/${reth_tag}^{}" '$2 == ref { print $1 }' <<<"$tag_refs")"
if [[ -z "$reth_commit" ]]; then
  reth_commit="$(awk -v ref="refs/tags/${reth_tag}" '$2 == ref { print $1 }' <<<"$tag_refs")"
fi
[[ "$reth_commit" =~ ^[0-9a-f]{40}$ ]] || {
  echo "official Reth tag ${reth_tag} was not found" >&2
  exit 1
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
upstream_manifest="$tmp/reth-Cargo.toml"
curl --fail --silent --show-error --location \
  "https://raw.githubusercontent.com/paradigmxyz/reth/${reth_commit}/Cargo.toml" \
  --output "$upstream_manifest"

rust_version="$(sed -nE 's/^[[:space:]]*rust-version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' \
  "$upstream_manifest" | head -n1)"
[[ "$rust_version" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || {
  echo "could not read Reth's minimum Rust version at ${reth_commit}" >&2
  exit 1
}
if [[ "$rust_version" =~ ^[0-9]+\.[0-9]+$ ]]; then
  rust_channel="${rust_version}.0"
else
  rust_channel="$rust_version"
fi

workspace_dependency_version() {
  local dependency="$1"
  local declaration
  local version

  declaration="$(
    grep -E "^${dependency}[[:space:]]*=" "$upstream_manifest" | head -n1
  )"
  version="$(
    sed -nE 's/.*version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' \
      <<<"$declaration"
  )"
  if [[ -z "$version" ]]; then
    version="$(
      sed -nE 's/^[^=]+=[[:space:]]*"([^"]+)".*/\1/p' <<<"$declaration"
    )"
  fi
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([+.-][0-9A-Za-z.-]+)?$ ]] || {
    echo "could not read Reth's ${dependency} version at ${reth_commit}" >&2
    exit 1
  }
  printf '%s\n' "$version"
}

# These crates cross the SlotScan/Reth API boundary. Keep one exact version in
# the graph so RPC, primitive, and inspector types cannot silently diverge.
alloy_primitives_version="$(workspace_dependency_version alloy-primitives)"
alloy_trace_version="$(workspace_dependency_version alloy-rpc-types-trace)"
jsonrpsee_version="$(workspace_dependency_version jsonrpsee)"
revm_inspectors_version="$(workspace_dependency_version revm-inspectors)"

RETH_COMMIT="$reth_commit" \
RETH_VERSION="$reth_version" \
SLOTSCAN_VERSION="$slotscan_version" \
RUST_CHANNEL="$rust_channel" \
RUST_VERSION="$rust_version" \
ALLOY_PRIMITIVES_VERSION="$alloy_primitives_version" \
ALLOY_TRACE_VERSION="$alloy_trace_version" \
JSONRPSEE_VERSION="$jsonrpsee_version" \
REVM_INSPECTORS_VERSION="$revm_inspectors_version" \
MANIFEST="$manifest" \
TOOLCHAIN="$toolchain" \
python3 <<'PY'
import os
import pathlib
import re

manifest_path = pathlib.Path(os.environ["MANIFEST"])
manifest = manifest_path.read_text()

manifest, package_count = re.subn(
    r'(?m)^version = "[^"]+"$',
    f'version = "{os.environ["SLOTSCAN_VERSION"]}"',
    manifest,
    count=1,
)
manifest, rust_count = re.subn(
    r'(?m)^rust-version = "[^"]+"$',
    f'rust-version = "{os.environ["RUST_VERSION"]}"',
    manifest,
    count=1,
)

reth_dependency = re.compile(
    r'(?m)^(reth-(?:ethereum|ethereum-cli|node-core|rpc-eth-api)'
    r' = \{ git = "https://github\.com/paradigmxyz/reth", rev = ")'
    r'([0-9a-f]{40})(".*\})$'
)
matches = reth_dependency.findall(manifest)
names = {match[0].split(" = ", 1)[0] for match in matches}
expected_names = {
    "reth-ethereum",
    "reth-ethereum-cli",
    "reth-node-core",
    "reth-rpc-eth-api",
}
old_revisions = {match[1] for match in matches}
if package_count != 1 or rust_count != 1:
    raise SystemExit("Cargo.toml package metadata did not match the expected shape")
if names != expected_names or len(matches) != len(expected_names):
    raise SystemExit("Cargo.toml Reth dependency set did not match the expected shape")
if len(old_revisions) != 1:
    raise SystemExit("Cargo.toml Reth dependencies were not pinned to one revision")

manifest = reth_dependency.sub(
    lambda match: f"{match.group(1)}{os.environ['RETH_COMMIT']}{match.group(3)}",
    manifest,
)

interface_dependencies = {
    "alloy-primitives": os.environ["ALLOY_PRIMITIVES_VERSION"],
    "alloy-rpc-types-trace": os.environ["ALLOY_TRACE_VERSION"],
    "jsonrpsee": os.environ["JSONRPSEE_VERSION"],
    "revm-inspectors": os.environ["REVM_INSPECTORS_VERSION"],
}
for dependency, version in interface_dependencies.items():
    pattern = re.compile(
        rf'(?m)^({re.escape(dependency)}\s*=\s*'
        rf'(?:\{{\s*version\s*=\s*)?")=[^"]+(".*)$'
    )
    manifest, count = pattern.subn(
        lambda match: f"{match.group(1)}={version}{match.group(2)}",
        manifest,
        count=1,
    )
    if count != 1:
        raise SystemExit(
            f"Cargo.toml {dependency} dependency did not match the expected shape"
        )

manifest_path.write_text(manifest)

toolchain_path = pathlib.Path(os.environ["TOOLCHAIN"])
toolchain = toolchain_path.read_text()
toolchain, count = re.subn(
    r'(?m)^channel = "[^"]+"$',
    f'channel = "{os.environ["RUST_CHANNEL"]}"',
    toolchain,
    count=1,
)
if count != 1:
    raise SystemExit("rust-toolchain.toml did not match the expected shape")
toolchain_path.write_text(toolchain)
PY

(
  cd "$crate"
  cargo update --package reth-ethereum
  cargo metadata --locked --format-version 1 >"$tmp/metadata.json"
)

RETH_COMMIT="$reth_commit" \
RETH_VERSION="$reth_version" \
SLOTSCAN_VERSION="$slotscan_version" \
ALLOY_PRIMITIVES_VERSION="$alloy_primitives_version" \
ALLOY_TRACE_VERSION="$alloy_trace_version" \
JSONRPSEE_VERSION="$jsonrpsee_version" \
REVM_INSPECTORS_VERSION="$revm_inspectors_version" \
METADATA="$tmp/metadata.json" \
python3 <<'PY'
import json
import os
import pathlib

metadata = json.loads(pathlib.Path(os.environ["METADATA"]).read_text())
packages = metadata["packages"]
root = next(package for package in packages if package["name"] == "reth-slotscan")
reth = next(package for package in packages if package["name"] == "reth-ethereum")

if root["version"] != os.environ["SLOTSCAN_VERSION"]:
    raise SystemExit("Cargo metadata contains the wrong SlotScan version")
if reth["version"] != os.environ["RETH_VERSION"]:
    raise SystemExit("Cargo metadata contains the wrong Reth version")
source = reth.get("source") or ""
if os.environ["RETH_COMMIT"] not in source:
    raise SystemExit("Cargo metadata did not resolve the exact Reth tag commit")

expected_dependencies = {
    "alloy-primitives": os.environ["ALLOY_PRIMITIVES_VERSION"],
    "alloy-rpc-types-trace": os.environ["ALLOY_TRACE_VERSION"],
    "jsonrpsee": os.environ["JSONRPSEE_VERSION"],
    "revm-inspectors": os.environ["REVM_INSPECTORS_VERSION"],
}
dependencies = {dependency["name"]: dependency for dependency in root["dependencies"]}
for name, version in expected_dependencies.items():
    requirement = dependencies.get(name, {}).get("req")
    if requirement != f"={version}":
        raise SystemExit(
            f"Cargo metadata contains the wrong {name} requirement: {requirement}"
        )
PY

[[ -s "$lockfile" ]] || { echo "Cargo.lock was not generated" >&2; exit 1; }
echo "prepared SlotScan Reth ${slotscan_version} at Reth commit ${reth_commit}"
