from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import create_database_engine
from app.models.database import (
    CompilerArtifact,
    Contract,
    ContractSourceCache,
    HistoricalContractResolution,
    TransactionTraceArtifact,
)
from app.models.domain import (
    ContractMetadata,
    RawCompilerArtifact,
    StorageLayout,
    VerificationResult,
)
from app.repositories.compiler_artifacts import CompilerArtifactRepository
from app.repositories.contracts import ContractRepository
from app.repositories.source_cache import SourceCacheRepository
from app.repositories.trace_cache import (
    TraceCacheRepository,
    TransactionTraceArtifactData,
)
from app.services.transaction_receipt import ReceiptIdentity
from tests.sqlite_utils import upgrade_database


ADDRESS = "0x" + "11" * 20
CODE_HASH = "0x" + "aa" * 32


class SQLiteRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_cache_tables_round_trip_replace_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "slotscan.sqlite3"
            upgrade_database(database_path)
            engine = create_database_engine(database_path)
            session_factory = async_sessionmaker(engine, expire_on_commit=False)

            large_json = {
                "blob": "x" * (2 * 1024 * 1024),
                "large_integer": 2**200,
                "items": [None, True, False, 1, "value"],
            }
            layout = StorageLayout(
                contract_name="Initial",
                variables=[],
                types={},
                language="Solidity",
            )
            initial_metadata = ContractMetadata(
                chain_id=1,
                address=ADDRESS,
                code_hash=CODE_HASH,
                is_verified=True,
                verification_source="etherscan",
                name="Initial",
                compiler_version="0.8.30",
                storage_layout=layout,
                compiler_artifact_fingerprint="11" * 32,
                layout_provenance="verified_exact",
                layout_source_address=ADDRESS,
            )
            updated_metadata = replace(initial_metadata, name="Updated")
            initial_artifact = RawCompilerArtifact(
                fingerprint="11" * 32,
                language="Solidity",
                compiler_version="0.8.30",
                pipeline="verified-layout",
                standard_input={"language": "Solidity"},
                compiler_output={"version": 1, "payload": large_json},
                source_hashes={"Contract.sol": "22" * 32},
            )
            updated_artifact = replace(
                initial_artifact,
                compiler_output={"version": 2, "payload": large_json},
            )
            initial_trace = TransactionTraceArtifactData(
                chain_id=1,
                tx_hash="0x" + "33" * 32,
                block_hash="0x" + "44" * 32,
                block_number=20_000_000,
                transaction_index=1,
                root_succeeded=True,
                write_events=[{"slot": "0x0", "value": "0x1"}],
                prestate_diff={"accounts": []},
                preimage_lookup={"0x01": "0x02"},
                capabilities={"complete": True},
            )
            updated_trace = replace(
                initial_trace,
                block_hash="0x" + "55" * 32,
                block_number=20_000_001,
                transaction_index=2,
                root_succeeded=False,
                write_events=[{"slot": "0x0", "value": "0x2"}],
            )

            try:
                async with session_factory() as session:
                    contract_repository = ContractRepository(session)
                    await contract_repository.save(initial_metadata)
                    await contract_repository.save_at_block(
                        initial_metadata,
                        block_number=20_000_000,
                    )
                    await CompilerArtifactRepository(session).save(initial_artifact)
                    await SourceCacheRepository(session).save_verified(
                        1,
                        ADDRESS,
                        CODE_HASH,
                        VerificationResult(
                            source="etherscan",
                            match_type="exact_match",
                            name="Initial",
                            sources={"Contract.sol": "contract Initial {}"},
                        ),
                    )
                    await TraceCacheRepository(session).save(initial_trace)

                async with session_factory() as session:
                    contract_repository = ContractRepository(session)
                    await contract_repository.save(updated_metadata)
                    await contract_repository.save_at_block(
                        updated_metadata,
                        block_number=20_000_000,
                    )
                    await CompilerArtifactRepository(session).save(updated_artifact)
                    await SourceCacheRepository(session).save_not_found(
                        1,
                        ADDRESS,
                        CODE_HASH,
                    )
                    await TraceCacheRepository(session).save(updated_trace)

                async with session_factory() as session:
                    contract = await ContractRepository(session).get(1, ADDRESS)
                    historical = await ContractRepository(session).get_at_block(
                        1,
                        ADDRESS,
                        20_000_000,
                    )
                    artifact = await CompilerArtifactRepository(session).get(
                        initial_artifact.fingerprint
                    )
                    source = await SourceCacheRepository(session).get(
                        1,
                        ADDRESS,
                        CODE_HASH,
                    )
                    trace_repository = TraceCacheRepository(session)
                    old_trace = await trace_repository.get(
                        1,
                        initial_trace.tx_hash,
                        ReceiptIdentity(
                            block_hash=initial_trace.block_hash,
                            block_number=initial_trace.block_number,
                            transaction_index=initial_trace.transaction_index,
                            root_succeeded=initial_trace.root_succeeded,
                        ),
                    )
                    new_trace = await trace_repository.get(
                        1,
                        updated_trace.tx_hash,
                        ReceiptIdentity(
                            block_hash=updated_trace.block_hash,
                            block_number=updated_trace.block_number,
                            transaction_index=updated_trace.transaction_index,
                            root_succeeded=updated_trace.root_succeeded,
                        ),
                    )
                    created_at = contract.created_at
                    checked_at = source.checked_at

                    self.assertEqual(contract.name, "Updated")
                    self.assertEqual(historical.name, "Updated")
                    self.assertEqual(artifact.compiler_output["version"], 2)
                    self.assertEqual(artifact.compiler_output["payload"], large_json)
                    self.assertEqual(source.status, "not_found")
                    self.assertIsNone(source.result)
                    self.assertIsNone(old_trace)
                    self.assertEqual(new_trace.write_events, updated_trace.write_events)
                    self.assertIsNone(created_at.tzinfo)
                    self.assertIsNone(checked_at.tzinfo)
            finally:
                await engine.dispose()

            reopened_engine = create_database_engine(database_path)
            reopened_factory = async_sessionmaker(
                reopened_engine,
                expire_on_commit=False,
            )
            try:
                async with reopened_factory() as session:
                    for model in (
                        Contract,
                        HistoricalContractResolution,
                        CompilerArtifact,
                        ContractSourceCache,
                        TransactionTraceArtifact,
                    ):
                        count = await session.scalar(
                            select(func.count()).select_from(model)
                        )
                        self.assertEqual(count, 1)

                    reopened_contract = await ContractRepository(session).get(
                        1,
                        ADDRESS,
                    )
                    reopened_source = await SourceCacheRepository(session).get(
                        1,
                        ADDRESS,
                        CODE_HASH,
                    )
                    self.assertEqual(reopened_contract.created_at, created_at)
                    self.assertEqual(reopened_source.checked_at, checked_at)
            finally:
                await reopened_engine.dispose()


if __name__ == "__main__":
    unittest.main()
