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
  --datadir "$tmp/data" \
  --chain dev \
  --port 30308 \
  --storage.v2 \
  --authrpc.jwtsecret "$tmp/jwt.hex" \
  --authrpc.addr 127.0.0.1 \
  --authrpc.port 18551 \
  --http \
  --http.addr 127.0.0.1 \
  --http.port 18545 \
  --http.api eth,net,web3,debug,trace,txpool \
  --rpc.max-blocks-per-filter 0 \
  --ws \
  --ws.addr 127.0.0.1 \
  --ws.port 18546 \
  --ws.api eth,net,web3 \
  --log.file.directory "$tmp/logs" \
  --metrics 127.0.0.1:19001 \
  >"$tmp/reth.log" 2>&1 &
pid=$!

rpc_url="http://127.0.0.1:18545"
deadline=$((SECONDS + 120))
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
