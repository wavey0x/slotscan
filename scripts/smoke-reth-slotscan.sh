#!/usr/bin/env bash
set -Eeuo pipefail

binary="${1:?usage: smoke-reth-slotscan.sh /path/to/reth}"
[[ -x "$binary" ]] || { echo "binary is not executable: $binary" >&2; exit 1; }

tmp="$(mktemp -d)"
pid=""
cleanup() {
  if [[ -n "$pid" ]]; then
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

printf '%064d\n' 0 >"$tmp/jwt.hex"
"$binary" node \
  --dev \
  --with-unused-ports \
  --ipcdisable \
  --datadir "$tmp/data" \
  --chain dev \
  --storage.v2 \
  --authrpc.jwtsecret "$tmp/jwt.hex" \
  --authrpc.addr 127.0.0.1 \
  --http \
  --http.addr 127.0.0.1 \
  --http.api eth,net,web3,debug,trace,txpool \
  --rpc.max-blocks-per-filter 0 \
  --log.file.directory "$tmp/logs" \
  >"$tmp/reth.log" 2>&1 &
pid=$!

deadline=$((SECONDS + 120))
rpc_address=""
until [[ -n "$rpc_address" ]]; do
  rpc_address="$(
    grep -F "RPC HTTP server started" "$tmp/reth.log" 2>/dev/null \
      | grep -oE '127\.0\.0\.1:[0-9]+' \
      | tail -n1 \
      || true
  )"
  [[ -n "$rpc_address" ]] && break
  if ! kill -0 "$pid" 2>/dev/null; then
    cat "$tmp/reth.log" >&2
    exit 1
  fi
  (( SECONDS < deadline )) || {
    cat "$tmp/reth.log" >&2
    echo "Reth RPC did not publish its listening address" >&2
    exit 1
  }
  sleep 1
done

rpc_url="http://$rpc_address"
until chain_response="$(curl --max-time 3 -fsS -X POST "$rpc_url" \
  -H 'content-type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' 2>/dev/null)"; do
  if ! kill -0 "$pid" 2>/dev/null; then
    cat "$tmp/reth.log" >&2
    exit 1
  fi
  (( SECONDS < deadline )) || {
    cat "$tmp/reth.log" >&2
    echo "Reth RPC did not become ready" >&2
    exit 1
  }
  sleep 2
done

grep -Fq '"result":"0x539"' <<<"$chain_response"

debug_response="$(curl --max-time 10 -fsS -X POST "$rpc_url" \
  -H 'content-type: application/json' \
  --data '{"jsonrpc":"2.0","id":2,"method":"debug_traceCall","params":[{"from":"0x0000000000000000000000000000000000000000","to":"0x0000000000000000000000000000000000000000","gas":"0x5208"},"latest",{"tracer":"{step:function(log,db){},fault:function(log,db){},result:function(ctx,db){return '\''ok'\'';}}"}]}' \
)"
grep -Fq '"result":"ok"' <<<"$debug_response"

slotscan_response="$(curl --max-time 10 -fsS -X POST "$rpc_url" \
  -H 'content-type: application/json' \
  --data '{"jsonrpc":"2.0","id":3,"method":"slotscan_traceTransaction","params":["0x0000000000000000000000000000000000000000000000000000000000000000",{"maxSteps":5000000,"maxWrites":10000,"maxSha3Operations":20000,"maxPreimageBytes":5242880,"maxObservedStorage":100000}]}' \
)"
grep -Eq '"code"[[:space:]]*:[[:space:]]*-32000' <<<"$slotscan_response"
grep -Fq '"message":"transaction not found"' <<<"$slotscan_response"
