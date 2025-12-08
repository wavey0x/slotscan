"""Debug script to see what SHA3 preimages are captured."""
import asyncio
import json
from web3 import AsyncWeb3

# Transaction and contract from the test case
TX_HASH = "0xe42fc6acb03f43c32a920c6521b2594a0a3c66252929364f1caaff6f81e40fbd"
CONTRACT = "0x22222222E9fE38F6f1FC8C61b25228adB4D8B953".lower()

# Unmatched slots we need to find
UNMATCHED_SLOTS = [
    "0x55bd702e64d2b1d4e26b159c2cf94f7b2831a77c184cfc30eefb12cf49581478",
    "0x55bd702e64d2b1d4e26b159c2cf94f7b2831a77c184cfc30eefb12cf49581479",
    "0x707063001b5a0697dac82a4022b4092f2ecbf5fb0b49862bffd9053fbcd4af0a",
    "0x6f45a6348dada5a17a5fcb52a3ddaf1f72360a0dcc247ddfb7852b66cac048f0",
]

STORAGE_TRACER = """{
    sstores: [],
    sha3s: [],
    index: 0,
    pendingSha3: null,
    step: function(log, db) {
        var op = log.op.toString();

        // If we have a pending SHA3, capture its result (now on top of stack)
        if (this.pendingSha3 !== null) {
            this.pendingSha3.hash = toHex(log.stack.peek(0));
            this.sha3s.push(this.pendingSha3);
            this.pendingSha3 = null;
        }

        if (op === "SSTORE") {
            this.sstores.push({
                address: toHex(log.contract.getAddress()),
                pc: log.getPC(),
                slot: toHex(log.stack.peek(0)),
                value: toHex(log.stack.peek(1)),
                depth: log.getDepth(),
                index: this.index++
            });
        } else if (op === "SHA3" || op === "KECCAK256") {
            // SHA3/KECCAK256: stack has [offset, size]
            var offset = log.stack.peek(0).valueOf();
            var size = log.stack.peek(1).valueOf();
            // Only capture mapping-sized preimages (64 bytes for single mapping, up to 128 for nested)
            if (size >= 64 && size <= 128) {
                var preimage = toHex(log.memory.slice(offset, offset + size));
                this.pendingSha3 = {
                    address: toHex(log.contract.getAddress()),
                    preimage: preimage,
                    size: size,
                    depth: log.getDepth()
                };
            }
        }
    },
    fault: function(log, db) {},
    result: function(ctx, db) {
        return {sstores: this.sstores, sha3s: this.sha3s};
    }
}"""

def normalize_slot(slot: str) -> str:
    """Normalize a slot to 0x-prefixed, 64-char hex."""
    if not slot.startswith("0x"):
        slot = "0x" + slot
    hex_part = slot[2:]
    padded = hex_part.zfill(64)
    return "0x" + padded

async def main():
    # Connect to Ethereum mainnet
    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("https://ethereum.publicnode.com"))

    print(f"Tracing transaction: {TX_HASH}")
    print(f"Target contract: {CONTRACT}")
    print()

    # Execute the trace
    result = await w3.provider.make_request(
        "debug_traceTransaction", [TX_HASH, {"tracer": STORAGE_TRACER}]
    )

    if "error" in result:
        print(f"Error: {result['error']}")
        return

    trace = result.get("result", {})
    sstores = trace.get("sstores", [])
    sha3s = trace.get("sha3s", [])

    print(f"Captured {len(sstores)} SSTORE operations")
    print(f"Captured {len(sha3s)} SHA3 operations")
    print()

    # Filter SHA3s for our contract
    contract_sha3s = [s for s in sha3s if s.get("address", "").lower() == CONTRACT]
    print(f"SHA3s for our contract: {len(contract_sha3s)}")
    print()

    # Build preimage lookup
    preimage_lookup = {}
    for op in contract_sha3s:
        hash_val = op.get("hash")
        preimage = op.get("preimage")
        if hash_val and preimage:
            normalized = normalize_slot(hash_val)
            preimage_lookup[normalized] = preimage

    print(f"Preimage lookup has {len(preimage_lookup)} entries")
    print()

    # Check if unmatched slots are in preimage lookup
    print("Checking unmatched slots:")
    for slot in UNMATCHED_SLOTS:
        normalized = normalize_slot(slot)
        if normalized in preimage_lookup:
            preimage = preimage_lookup[normalized]
            print(f"  {slot[:18]}... FOUND!")
            print(f"    Preimage: {preimage}")
            # Parse the preimage
            preimage_clean = preimage[2:] if preimage.startswith("0x") else preimage
            if len(preimage_clean) >= 128:
                key_hex = "0x" + preimage_clean[:64]
                base_slot = "0x" + preimage_clean[64:128]
                print(f"    Key: {key_hex}")
                print(f"    Base slot: {base_slot}")
        else:
            print(f"  {slot[:18]}... NOT in preimage lookup")
            # Check if slot - offset is in preimage lookup
            slot_int = int(slot, 16)
            for offset in range(1, 5):
                base_int = slot_int - offset
                base_hex = normalize_slot(hex(base_int))
                if base_hex in preimage_lookup:
                    print(f"    BUT slot - {offset} IS in lookup!")
                    preimage = preimage_lookup[base_hex]
                    print(f"    Base preimage: {preimage}")

    print()
    print("All SHA3 hashes in lookup:")
    for hash_val in sorted(preimage_lookup.keys())[:20]:
        preimage = preimage_lookup[hash_val]
        preimage_clean = preimage[2:] if preimage.startswith("0x") else preimage
        if len(preimage_clean) >= 128:
            key_hex = "0x" + preimage_clean[:64]
            base_slot = "0x" + preimage_clean[64:128]
            base_int = int(base_slot, 16)
            # Check if key looks like an address (first 12 bytes zero)
            if preimage_clean[:24] == "0" * 24:
                addr = "0x" + preimage_clean[24:64]
                print(f"  {hash_val[:18]}... = keccak(addr:{addr[:10]}..., slot:{base_int})")
            else:
                key_int = int(key_hex, 16)
                if key_int < 1000:
                    print(f"  {hash_val[:18]}... = keccak(uint:{key_int}, slot:{base_int})")
                else:
                    print(f"  {hash_val[:18]}... = keccak({key_hex[:10]}..., slot:{base_int})")

if __name__ == "__main__":
    asyncio.run(main())
