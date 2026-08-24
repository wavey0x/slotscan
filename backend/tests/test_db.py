import asyncio
from pathlib import Path
import tempfile
import unittest

from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import create_database_engine
from app.models.database import (
    CompilerArtifact,
    ContractSourceCache,
    HistoricalContractResolution,
)
from app.models.domain import ContractMetadata, RawCompilerArtifact
from app.repositories.compiler_artifacts import CompilerArtifactRepository
from app.repositories.contracts import ContractRepository
from app.repositories.source_cache import SourceCacheRepository
from tests.sqlite_utils import run_alembic, upgrade_database


EXPECTED_COLUMNS = {
    "contracts": {
        "id",
        "chain_id",
        "address",
        "name",
        "code_hash",
        "is_proxy",
        "proxy_type",
        "implementation_address",
        "is_verified",
        "verification_source",
        "compiler_version",
        "compiler_artifact_fingerprint",
        "layout_provenance",
        "layout_source_address",
        "storage_layout",
        "created_at",
        "updated_at",
        "verified_at",
        "source_checked_at",
    },
    "transaction_trace_artifacts": {
        "id",
        "chain_id",
        "tx_hash",
        "block_hash",
        "block_number",
        "transaction_index",
        "root_succeeded",
        "transaction_from",
        "transaction_to",
        "created_contract",
        "write_events",
        "prestate_diff",
        "preimage_lookup",
        "capabilities",
        "trace_step_count",
        "write_count",
        "created_at",
    },
    "compiler_artifacts": {
        "id",
        "fingerprint",
        "language",
        "compiler_version",
        "pipeline",
        "standard_input",
        "compiler_output",
        "source_hashes",
        "created_at",
    },
    "historical_contract_resolutions": {
        "id",
        "chain_id",
        "address",
        "block_number",
        "code_hash",
        "is_proxy",
        "proxy_type",
        "implementation_address",
        "is_verified",
        "verification_source",
        "name",
        "compiler_version",
        "compiler_artifact_fingerprint",
        "layout_provenance",
        "layout_source_address",
        "storage_layout",
        "created_at",
        "source_checked_at",
    },
    "contract_source_cache": {
        "id",
        "chain_id",
        "code_address",
        "code_hash",
        "status",
        "result",
        "checked_at",
    },
}


class SQLiteMigrationTests(unittest.TestCase):
    def test_fresh_baseline_matches_models_and_alembic_check(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "slotscan.sqlite3"
            upgrade_database(database_path)
            run_alembic(database_path, "check")

            sync_engine = create_engine(
                URL.create("sqlite", database=str(database_path))
            )
            try:
                inspector = inspect(sync_engine)
                self.assertEqual(
                    set(inspector.get_table_names()),
                    {*EXPECTED_COLUMNS, "alembic_version"},
                )
                for table_name, expected_columns in EXPECTED_COLUMNS.items():
                    self.assertEqual(
                        {column["name"] for column in inspector.get_columns(table_name)},
                        expected_columns,
                    )

                indexes = {
                    index["name"]: (tuple(index["column_names"]), index["unique"])
                    for table_name in EXPECTED_COLUMNS
                    for index in inspector.get_indexes(table_name)
                }
                self.assertEqual(
                    indexes,
                    {
                        "idx_contracts_chain_address": (
                            ("chain_id", "address"),
                            1,
                        ),
                        "idx_contracts_code_hash": (("code_hash",), 0),
                        "idx_transaction_trace_artifacts_lookup": (
                            ("chain_id", "tx_hash"),
                            1,
                        ),
                        "idx_compiler_artifacts_fingerprint": (
                            ("fingerprint",),
                            1,
                        ),
                        "idx_historical_contract_resolution_lookup": (
                            ("chain_id", "address", "block_number"),
                            1,
                        ),
                    },
                )

                source_uniques = inspector.get_unique_constraints(
                    "contract_source_cache"
                )
                self.assertIn(
                    {
                        "name": "uq_contract_source_cache_identity",
                        "column_names": ["chain_id", "code_address", "code_hash"],
                    },
                    source_uniques,
                )
                source_checks = inspector.get_check_constraints(
                    "contract_source_cache"
                )
                self.assertEqual(
                    [constraint["name"] for constraint in source_checks],
                    ["ck_contract_source_cache_status"],
                )
                self.assertIn("'verified'", source_checks[0]["sqltext"])
                self.assertIn("'not_found'", source_checks[0]["sqltext"])
            finally:
                sync_engine.dispose()


class SQLiteContentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_engine_policy_and_eight_resolver_style_writers(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "slotscan.sqlite3"
            upgrade_database(database_path)
            engine = create_database_engine(database_path)
            session_factory = async_sessionmaker(engine, expire_on_commit=False)

            try:
                async with engine.connect() as connection:
                    journal_mode = await connection.scalar(
                        text("PRAGMA journal_mode")
                    )
                    busy_timeout = await connection.scalar(
                        text("PRAGMA busy_timeout")
                    )
                    foreign_keys = await connection.scalar(
                        text("PRAGMA foreign_keys")
                    )
                self.assertEqual(journal_mode, "wal")
                self.assertEqual(busy_timeout, 5000)
                self.assertEqual(foreign_keys, 1)

                async def write_resolution(index: int) -> None:
                    address = "0x" + f"{index + 1:040x}"
                    code_hash = "0x" + f"{index + 1:064x}"
                    fingerprint = f"{index + 1:064x}"
                    async with session_factory() as session:
                        await SourceCacheRepository(session).save_not_found(
                            1,
                            address,
                            code_hash,
                        )
                        await CompilerArtifactRepository(session).save(
                            RawCompilerArtifact(
                                fingerprint=fingerprint,
                                language="Solidity",
                                compiler_version="0.8.30",
                                pipeline="contention-test",
                                standard_input={"index": index},
                                compiler_output={"ok": True},
                                source_hashes={"Contract.sol": fingerprint},
                            )
                        )
                        await ContractRepository(session).save_at_block(
                            ContractMetadata(
                                chain_id=1,
                                address=address,
                                code_hash=code_hash,
                                name=f"Contract{index}",
                            ),
                            block_number=20_000_000,
                        )

                await asyncio.gather(*(write_resolution(index) for index in range(8)))

                async with session_factory() as session:
                    for model in (
                        ContractSourceCache,
                        CompilerArtifact,
                        HistoricalContractResolution,
                    ):
                        count = await session.scalar(
                            select(func.count()).select_from(model)
                        )
                        self.assertEqual(count, 8)
            finally:
                await engine.dispose()


if __name__ == "__main__":
    unittest.main()
