"""Transaction-level RPC evidence extraction, independent of decoding/layouts."""

from dataclasses import dataclass

from app.services.tracer.rpc_client import TraceRPCClient


@dataclass(frozen=True)
class TransactionTraceEvidence:
    receipt: dict
    prestate_diff: dict
    writes: list[dict]
    sha3_operations: list[dict]
    evm_step_count: int


class TransactionTraceExtractor:
    """Fetch canonical raw evidence once for all touched contracts."""

    def __init__(self, rpc_client: TraceRPCClient):
        self.rpc_client = rpc_client

    async def extract(self, chain_id: int, tx_hash: str) -> TransactionTraceEvidence:
        # Receipt and prestate calls are deliberately kept together here so
        # contract projections never issue their own transaction trace.
        import asyncio

        prestate_diff, receipt = await asyncio.gather(
            self.rpc_client.execute_prestate_trace(chain_id, tx_hash),
            self.rpc_client.get_receipt(chain_id, tx_hash),
        )
        tx_to_address = receipt.get("to") or receipt.get("contractAddress")
        writes, sha3_operations, evm_step_count = (
            await self.rpc_client.execute_structlogs_trace(
                chain_id,
                tx_hash,
                tx_to_address,
            )
        )
        return TransactionTraceEvidence(
            receipt=receipt,
            prestate_diff=prestate_diff,
            writes=writes,
            sha3_operations=sha3_operations,
            evm_step_count=evm_step_count,
        )
