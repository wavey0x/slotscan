# Transaction Tracer Service

## Overview

The Transaction Tracer extracts storage changes (SSTORE operations) from a transaction using debug trace APIs. It maps raw slot changes to the contract's storage layout and produces a decoded diff showing before/after values.
MVP constraints: single contract per request, Postgres as the only cache, all work is in-request. If tracing fails or times out, return a graceful "trace unavailable" response instead of 500.

## Implementation Status: ✅ Complete

### Key Implementation Decisions

1. **Mapping Key Inference via Candidate Addresses**: The tracer collects candidate addresses from:
   - Transaction receipt: `from`, `to` addresses
   - Log-emitting contract addresses
   - Log topics (address-padded 32-byte values like ERC20 Transfer events)
   - Log data (32-byte chunks that look like addresses)
   - Trace state: contract addresses and storage values that look like addresses

   For each unmatched slot, it computes `keccak256(candidate || base_slot)` for address-keyed mappings and matches if slot matches.

2. **No Weak Mapping Inference**: Previously, unmatched slots were speculatively assigned to the first mapping variable found. This was removed because it produced misleading results (e.g., array slots labeled as mapping entries). Unmatched slots now remain unattributed with `variable=None`.

3. **Graceful Degradation**: If `debug_traceTransaction` is unavailable, returns `trace_unavailable=True` with empty changes instead of failing.

4. **Value Type Decoding for Mappings**: When a mapping is matched, decodes using the mapping's value type (not the mapping type itself) for proper display.

## Location

```
backend/app/services/tracer.py
```

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `web3.py` | RPC calls (`debug_traceTransaction`, `eth_getTransactionReceipt`) |
| Layout Parser | StorageLayout for mapping slots to variables |
| Type Decoder | Decode raw values |
| Database Layer | Cache transaction diffs (Postgres JSONB) |

## Public Interface

```python
@dataclass
class StorageChange:
    """A single storage slot change in a transaction."""
    slot: str                       # Hex slot index
    old_value: str                  # Hex bytes32 before
    new_value: str                  # Hex bytes32 after
    variable: Optional[StorageVariable]  # Matched variable (if layout)
    variable_path: Optional[str]    # e.g., "balances[0x...]"
    old_decoded: Optional[Any]      # Decoded before value
    new_decoded: Optional[Any]      # Decoded after value


@dataclass
class TransactionDiff:
    """All storage changes for a contract in a transaction."""
    chain_id: int
    contract_address: str
    tx_hash: str
    block_number: int
    changes: List[StorageChange]
    is_complete: bool               # False if truncated
    layout: Optional[StorageLayout]  # Layout used (if verified)


class TransactionTracer:
    """Traces transactions to extract storage changes."""

    async def trace_transaction(
        self,
        chain_id: int,
        contract_address: str,
        tx_hash: str,
        layout: Optional[StorageLayout] = None
    ) -> TransactionDiff:
        """
        Trace a transaction and extract storage changes for a contract.

        Uses debug_traceTransaction with prestateTracer to get
        before/after storage values for all touched slots.

        Args:
            chain_id: Chain ID
            contract_address: Target contract to filter changes
            tx_hash: Transaction hash to trace
            layout: Storage layout for decoding (optional)

    Returns:
        TransactionDiff with all storage changes

    Raises:
        TransactionNotFoundError: If tx doesn't exist
        TraceNotAvailableError: If node doesn't support tracing (gracefully handled to return degraded response)
        """
        pass

    async def get_transaction_block(
        self,
        chain_id: int,
        tx_hash: str
    ) -> int:
        """Get the block number a transaction was included in."""
        pass
```

## Implementation Details

### 1. Transaction Lookup

```python
async def get_transaction_block(self, chain_id: int, tx_hash: str) -> int:
    """
    Get block number for a transaction.

    Used to determine the block for storage state context.
    """
    web3 = self.web3_provider.get_web3(chain_id)

    try:
        receipt = await web3.eth.get_transaction_receipt(tx_hash)
    except Exception as e:
        raise TransactionNotFoundError(tx_hash)

    if receipt is None:
        raise TransactionNotFoundError(tx_hash)

    return receipt["blockNumber"]
```

### 2. Debug Trace Execution

```python
async def _execute_trace(
    self,
    chain_id: int,
    tx_hash: str
) -> Dict:
    """
    Execute debug_traceTransaction with prestateTracer.

    The prestateTracer returns the state (storage, balance, nonce)
    before AND after the transaction for all touched accounts.

    Response format:
    {
        "pre": {
            "0xContract...": {
                "storage": {
                    "0x0": "0x...",  // slot -> value before
                    "0x1": "0x..."
                }
            }
        },
        "post": {
            "0xContract...": {
                "storage": {
                    "0x0": "0x...",  // slot -> value after
                    "0x1": "0x..."
                }
            }
        }
    }
    """
    web3 = self.web3_provider.get_web3(chain_id)

    tracer_config = {
        "tracer": "prestateTracer",
        "tracerConfig": {
            "diffMode": True  # Get pre and post state
        }
    }

    try:
        result = await web3.provider.make_request(
            "debug_traceTransaction",
            [tx_hash, tracer_config]
        )
    except Exception as e:
        error_msg = str(e).lower()
        if "method not found" in error_msg or "not supported" in error_msg:
            raise TraceNotAvailableError(
                "Node does not support debug_traceTransaction"
            )
        raise RPCError("debug_traceTransaction", str(e))

    if "error" in result:
        raise RPCError("debug_traceTransaction", result["error"])

    return result.get("result", {})


async def _execute_trace_alternative(
    self,
    chain_id: int,
    tx_hash: str
) -> Dict:
    """
    Alternative trace method using custom tracer.

    Some nodes may not support prestateTracer but support custom JS tracers.
    This provides a fallback.
    """
    # Custom tracer that captures SSTOREs
    custom_tracer = """
    {
        data: [],
        fault: function(log) {},
        step: function(log) {
            if (log.op.toString() === "SSTORE") {
                this.data.push({
                    address: toHex(log.contract.getAddress()),
                    slot: toHex(log.stack.peek(0)),
                    value: toHex(log.stack.peek(1))
                });
            }
        },
        result: function() { return this.data; }
    }
    """

    web3 = self.web3_provider.get_web3(chain_id)

    try:
        result = await web3.provider.make_request(
            "debug_traceTransaction",
            [tx_hash, {"tracer": custom_tracer}]
        )
        return self._convert_custom_trace(result.get("result", []))
    except Exception:
        raise TraceNotAvailableError("Tracing not available")
```

### 3. Trace Parsing

```python
def _extract_contract_changes(
    self,
    trace_result: Dict,
    contract_address: str
) -> List[Tuple[str, str, str]]:
    """
    Extract storage changes for a specific contract from trace.

    Returns list of (slot, old_value, new_value) tuples.
    """
    contract_address = contract_address.lower()
    changes = []

    pre_state = trace_result.get("pre", {})
    post_state = trace_result.get("post", {})

    # Find contract in pre/post (address may be checksummed differently)
    pre_storage = {}
    post_storage = {}

    for addr, state in pre_state.items():
        if addr.lower() == contract_address:
            pre_storage = state.get("storage", {})
            break

    for addr, state in post_state.items():
        if addr.lower() == contract_address:
            post_storage = state.get("storage", {})
            break

    # Collect all slots that appear in either pre or post
    all_slots = set(pre_storage.keys()) | set(post_storage.keys())

    zero_value = "0x" + "00" * 32

    for slot in all_slots:
        old_val = pre_storage.get(slot, zero_value)
        new_val = post_storage.get(slot, zero_value)

        # Normalize values to full 32-byte hex
        old_val = self._normalize_value(old_val)
        new_val = self._normalize_value(new_val)

        # Only include if changed
        if old_val != new_val:
            changes.append((slot, old_val, new_val))

    return changes


def _normalize_value(self, value: str) -> str:
    """
    Normalize a storage value to full 32-byte hex.

    Trace results may return shortened values (e.g., "0x1" instead of "0x000...001").
    """
    if not value.startswith("0x"):
        value = "0x" + value

    # Remove 0x prefix, pad to 64 chars, add prefix back
    hex_part = value[2:]
    padded = hex_part.zfill(64)
    return "0x" + padded
```

### 4. Change Decoding

```python
def _decode_changes(
    self,
    raw_changes: List[Tuple[str, str, str]],
    layout: Optional[StorageLayout]
) -> List[StorageChange]:
    """
    Convert raw slot changes to decoded StorageChange objects.

    If layout is available, maps slots to variables and decodes values.
    """
    decoded_changes = []

    for slot_hex, old_value, new_value in raw_changes:
        # Parse slot number
        slot_int = int(slot_hex, 16)

        # Try to map to variable
        variable = None
        variable_path = None
        old_decoded = None
        new_decoded = None

        if layout:
            # Find variable at this slot
            variable = layout.get_variable_by_slot(slot_int)

            if variable:
                var_type = layout.get_type(variable.type_id)
                variable_path = variable.name

                if var_type:
                    # Decode old and new values
                    old_decoded = self.decoder.decode(
                        bytes.fromhex(old_value[2:]),
                        var_type,
                        variable.offset
                    )
                    new_decoded = self.decoder.decode(
                        bytes.fromhex(new_value[2:]),
                        var_type,
                        variable.offset
                    )

            else:
                # Slot might be a mapping entry - try to identify
                variable_path = self._try_identify_mapping_slot(
                    slot_int, layout
                )

        decoded_changes.append(StorageChange(
            slot=slot_hex,
            old_value=old_value,
            new_value=new_value,
            variable=variable,
            variable_path=variable_path,
            old_decoded=old_decoded,
            new_decoded=new_decoded
        ))

    return decoded_changes


def _try_identify_mapping_slot(
    self,
    slot: int,
    layout: StorageLayout
) -> Optional[str]:
    """
    Try to identify which mapping a slot belongs to.

    This is heuristic-based since we can't reverse keccak256.
    We can only identify if we've seen this slot before in traces.
    """
    # Check if slot is in known mapping keys from database
    # This would require a lookup in our discovered_mapping_keys table
    # For now, return None (future enhancement)
    return None
```

### 5. Main Trace Flow

```python
async def trace_transaction(
    self,
    chain_id: int,
    contract_address: str,
    tx_hash: str,
    layout: Optional[StorageLayout] = None
) -> TransactionDiff:
    """
    Full tracing pipeline.

    1. Check cache
    2. Get block number
    3. Execute trace
    4. Extract contract changes
    5. Decode changes
    6. Cache and return
    """
    contract_address = Web3.to_checksum_address(contract_address)

    # Check cache first
    cached = await self.cache.get_tx_diff(chain_id, contract_address, tx_hash)
    if cached:
        return cached

    # Get block number
    block_number = await self.get_transaction_block(chain_id, tx_hash)

    # Execute trace
    trace_result = await self._execute_trace(chain_id, tx_hash)

    # Extract changes for our contract
    raw_changes = self._extract_contract_changes(trace_result, contract_address)

    # Check limits
    is_complete = len(raw_changes) <= self.config.max_sstore_ops
    if not is_complete:
        raw_changes = raw_changes[:self.config.max_sstore_ops]

    # Decode changes
    decoded_changes = self._decode_changes(raw_changes, layout)

    # Build result
    diff = TransactionDiff(
        chain_id=chain_id,
        contract_address=contract_address,
        tx_hash=tx_hash,
        block_number=block_number,
        changes=decoded_changes,
        is_complete=is_complete,
        layout=layout
    )

    # Cache result
    await self.cache.save_tx_diff(diff)

    return diff
```

### 6. Mapping Key Discovery

```python
async def discover_mapping_keys(
    self,
    chain_id: int,
    contract_address: str,
    tx_hash: str,
    layout: StorageLayout
) -> Dict[int, List[Any]]:
    """
    Attempt to discover mapping keys from transaction trace.

    This uses heuristics and event logs to identify keys:
    1. Parse Transfer events for address keys
    2. Parse function input data for key arguments
    3. Check known patterns (ERC20, ERC721, etc.)

    Returns dict of base_slot -> [discovered_keys]
    """
    # Get transaction input and logs
    web3 = self.web3_provider.get_web3(chain_id)
    tx = await web3.eth.get_transaction(tx_hash)
    receipt = await web3.eth.get_transaction_receipt(tx_hash)

    discovered = {}

    # Find mapping variables
    for var in layout.variables:
        var_type = layout.get_type(var.type_id)
        if var_type and var_type.encoding == "mapping":
            discovered[var.slot] = []

    # Parse Transfer events (ERC20 pattern)
    transfer_topic = Web3.keccak(text="Transfer(address,address,uint256)")
    for log in receipt.get("logs", []):
        if log["address"].lower() == contract_address.lower():
            if log["topics"] and log["topics"][0] == transfer_topic:
                # Extract from/to addresses
                if len(log["topics"]) >= 3:
                    from_addr = "0x" + log["topics"][1].hex()[-40:]
                    to_addr = "0x" + log["topics"][2].hex()[-40:]

                    # Add to potential mapping keys (assume balances mapping)
                    for slot in discovered:
                        discovered[slot].extend([from_addr, to_addr])

    # Parse Approval events (ERC20 pattern)
    approval_topic = Web3.keccak(text="Approval(address,address,uint256)")
    for log in receipt.get("logs", []):
        if log["address"].lower() == contract_address.lower():
            if log["topics"] and log["topics"][0] == approval_topic:
                if len(log["topics"]) >= 3:
                    owner = "0x" + log["topics"][1].hex()[-40:]
                    spender = "0x" + log["topics"][2].hex()[-40:]
                    for slot in discovered:
                        discovered[slot].extend([owner, spender])

    # Add tx sender/receiver as potential keys
    for slot in discovered:
        discovered[slot].append(tx["from"])
        if tx.get("to"):
            discovered[slot].append(tx["to"])

    # Deduplicate
    for slot in discovered:
        discovered[slot] = list(set(discovered[slot]))

    return discovered
```

## Configuration

```python
@dataclass
class TracerConfig:
    # Trace limits
    max_sstore_ops: int = 10000    # Max changes to process
    trace_timeout: float = 30.0    # Trace timeout

    # Fallback settings
    use_custom_tracer_fallback: bool = True

    # Key discovery
    enable_key_discovery: bool = True
```

## Error Handling

```python
class TransactionNotFoundError(Exception):
    """Raised when transaction doesn't exist."""
    def __init__(self, tx_hash: str):
        self.tx_hash = tx_hash
        super().__init__(f"Transaction not found: {tx_hash}")


class TraceNotAvailableError(Exception):
    """Raised when node doesn't support tracing."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Tracing not available: {reason}")
```

## Caching Strategy

| Data | Cache Key | TTL |
|------|-----------|-----|
| Transaction diff | `(chain_id, contract, tx_hash)` | Optional TTL (e.g., 30 minutes); immutable payload |
| Discovered keys | `(chain_id, contract, slot, key)` | Optional persistence |

If tracing fails or times out, return degraded response: `trace_unavailable=True`, empty changes, HTTP 200 with warning. Transaction diffs are immutable once confirmed.

Mapping context and readability:
- When a mapping variable is identified, include its base slot (unhashed) alongside the computed slot hash in responses to help users understand mapping slot derivation.
- Always return decoded values where possible (value type for mappings; heuristics otherwise) and include raw hex alongside for reference.
- Weak inference: if hashed slots cannot be inverted, still attach the mapping variable via base-slot context and render `mappingName[?]` to avoid raw/nameless slots.

## Testing Strategy

### Unit Tests

1. **Trace parsing**
   - Parse prestateTracer output
   - Handle missing pre/post state
   - Normalize value formats

2. **Change decoding**
   - Map slot to variable
   - Decode value types
   - Handle unknown slots

3. **Key discovery**
   - Parse Transfer events
   - Parse Approval events
   - Extract tx participants

### Integration Tests

1. **Real transaction tracing**
   - Trace simple transfer
   - Trace complex DeFi tx
   - Trace contract creation

2. **Error cases**
   - Non-existent transaction
   - Node without tracing
   - Reverted transaction

## Node Requirements

The tracer requires a node that supports `debug_traceTransaction`:

| Node Type | Support |
|-----------|---------|
| Geth (archive) | Full support |
| Erigon | Full support |
| Nethermind | Full support |
| Infura | Not supported |
| Alchemy | Supported (paid tier) |
| QuickNode | Supported (some plans) |

Degraded mode: if tracing is unavailable or times out, respond with `trace_unavailable=True` and no changes instead of failing the request. No retries beyond a single backoff attempt.

## Example Usage

```python
tracer = TransactionTracer(web3_provider, config, decoder, cache)

# Trace a transaction
diff = await tracer.trace_transaction(
    chain_id=1,
    contract_address="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    tx_hash="0xabc123...",
    layout=usdc_layout
)

print(f"Block: {diff.block_number}")
print(f"Changes: {len(diff.changes)}")

for change in diff.changes:
    print(f"  {change.variable_path}:")
    print(f"    {change.old_decoded} -> {change.new_decoded}")

# Get just the block number
block = await tracer.get_transaction_block(1, "0xabc123...")
```

## Example Trace Output

For a USDC transfer transaction:

```python
TransactionDiff(
    chain_id=1,
    contract_address="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    tx_hash="0xabc123...",
    block_number=19000000,
    changes=[
        StorageChange(
            slot="0x1a2b3c...",  # balances[sender]
            old_value="0x000...0064",  # 100
            new_value="0x000...0032",  # 50
            variable_path="balances[0xSender...]",
            old_decoded=100_000000,  # 100 USDC (6 decimals)
            new_decoded=50_000000    # 50 USDC
        ),
        StorageChange(
            slot="0x4d5e6f...",  # balances[receiver]
            old_value="0x000...0000",  # 0
            new_value="0x000...0032",  # 50
            variable_path="balances[0xReceiver...]",
            old_decoded=0,
            new_decoded=50_000000
        )
    ],
    is_complete=True
)
```
