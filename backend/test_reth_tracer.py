"""Test what tracers are available on the RPC."""
import asyncio
from web3 import AsyncWeb3

TX_HASH = "0xe42fc6acb03f43c32a920c6521b2594a0a3c66252929364f1caaff6f81e40fbd"

async def test_opcodes():
    # Use a Reth-friendly approach
    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider("https://ethereum.publicnode.com"))
    
    # Test 1: Basic trace with structLogs (should work on Reth)
    print("Testing structLogs tracer...")
    try:
        result = await w3.provider.make_request(
            "debug_traceTransaction",
            [TX_HASH, {"disableStorage": False, "disableStack": False, "disableMemory": False}]
        )
        if "error" in result:
            print(f"  Error: {result['error']}")
        else:
            struct_logs = result.get("result", {}).get("structLogs", [])
            print(f"  Success! Got {len(struct_logs)} opcode steps")
            # Look for SHA3/KECCAK256 opcodes
            sha3_ops = [op for op in struct_logs if op.get("op") in ("SHA3", "KECCAK256")]
            print(f"  SHA3/KECCAK256 operations: {len(sha3_ops)}")
            if sha3_ops:
                op = sha3_ops[0]
                print(f"  Example: op={op.get('op')}, stack={op.get('stack', [])[:3]}")
                print(f"    memory length={len(op.get('memory', []))}")
    except Exception as e:
        print(f"  Exception: {e}")

asyncio.run(test_opcodes())
