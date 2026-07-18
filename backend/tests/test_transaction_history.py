import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api.routes.transactions import (
    _group_changes_by_slot,
    get_transaction_storage_history,
)
from app.config import Settings
from app.models.domain import (
    ContractMetadata,
    StorageLayout,
    StorageType,
    StorageVariable,
)
from app.models.errors import RPCError, TraceNotAvailableError
from app.repositories.trace_cache import (
    TransactionTraceArtifactData,
)
from app.services.decoder import TypeDecoder
from app.services.tracer.tracer import (
    TraceSingleFlight,
    TransactionAnalysisService,
)
from app.services.tracer.extractor import (
    TransactionTraceEvidence,
    TransactionTraceExtractor,
)
from app.services.tracer.rpc_client import TraceRPCClient
from app.services.transaction_history import TransactionHistoryService


ADDRESS_A = "0x" + "11" * 20
ADDRESS_B = "0x" + "22" * 20
ADDRESS_C = "0x" + "33" * 20
CODE_A = "0x" + "aa" * 20
CODE_B = "0x" + "bb" * 20
ZERO = "0x" + "00" * 32
ONE = "0x" + "00" * 31 + "01"
FIVE = "0x" + "00" * 31 + "05"
SIX = "0x" + "00" * 31 + "06"
SLOT_1 = "0x" + "00" * 31 + "01"


def artifact() -> TransactionTraceArtifactData:
    return TransactionTraceArtifactData(
        chain_id=1,
        tx_hash="0x" + "ab" * 32,
        block_number=24_566_937,
        root_succeeded=True,
        transaction_from="0x" + "44" * 20,
        transaction_to=ADDRESS_A,
        created_contract=None,
        write_events=[
            {
                "address": ADDRESS_A,
                "code_address": CODE_A,
                "slot": SLOT_1,
                "value": ONE,
                "old_value": ZERO,
                "index": 10,
                "pc": 1,
                "depth": 1,
                "frame_id": 0,
                "frame_reverted": False,
                "opcode": "SSTORE",
                "namespace": "persistent",
            },
            {
                "address": ADDRESS_B,
                "code_address": ADDRESS_B,
                "slot": SLOT_1,
                "value": SIX,
                "old_value": FIVE,
                "index": 15,
                "pc": 2,
                "depth": 2,
                "frame_id": 1,
                "frame_reverted": True,
                "opcode": "SSTORE",
                "namespace": "persistent",
            },
            {
                "address": ADDRESS_A,
                "code_address": CODE_A,
                "slot": SLOT_1,
                "value": ZERO,
                "old_value": ONE,
                "index": 20,
                "pc": 3,
                "depth": 1,
                "frame_id": 0,
                "frame_reverted": False,
                "opcode": "SSTORE",
                "namespace": "persistent",
            },
            {
                "address": ADDRESS_A,
                "code_address": CODE_A,
                "slot": SLOT_1,
                "value": ZERO,
                "old_value": ZERO,
                "index": 30,
                "pc": 4,
                "depth": 1,
                "frame_id": 0,
                "frame_reverted": False,
                "opcode": "SSTORE",
                "namespace": "persistent",
            },
            {
                "address": ADDRESS_C,
                "code_address": ADDRESS_C,
                "slot": SLOT_1,
                "value": ONE,
                "old_value": ZERO,
                "index": 40,
                "pc": 5,
                "depth": 1,
                "frame_id": 0,
                "frame_reverted": False,
                "opcode": "TSTORE",
                "namespace": "transient",
            },
        ],
        prestate_diff={"pre": {}, "post": {}},
        preimage_lookup={},
        capabilities={
            "write_history_complete": True,
            "address_attribution_complete": True,
            "code_attribution_complete": True,
        },
        trace_step_count=100,
    )


class _NoopProvider:
    pass


class _CachedArtifactRepository:
    def __init__(self, value):
        self.value = value
        self.get_count = 0

    async def get(self, chain_id, tx_hash):
        self.get_count += 1
        return self.value


class _SharedArtifactRepository:
    def __init__(self):
        self.value = None
        self.save_count = 0

    async def get(self, chain_id, tx_hash):
        await asyncio.sleep(0)
        return self.value

    async def save(self, value):
        self.save_count += 1
        self.value = value


class _FailingHistoryService:
    async def analyze(self, chain_id, tx_hash):
        raise RPCError(
            "debug_traceTransaction",
            "https://user:secret@rpc.example/key?token=abc",
        )


class _CompactTraceProvider:
    def __init__(self):
        self.params = None

    async def make_request(self, chain_id, method, params):
        self.params = params
        return {
            "result": {
                "fatal": None,
                "executable": True,
                "hookEnters": 1,
                "hookExits": 1,
                "frameStack": [0],
                "writes": [
                    {
                        "slot": "0x1",
                        "value": "0x1",
                        "old_value": None,
                        "opcode": "SSTORE",
                        "namespace": "persistent",
                        "pc": 1,
                        "depth": 1,
                        "index": 5,
                        "frame_id": 0,
                    },
                    {
                        "slot": "0x2",
                        "value": "0x2",
                        "old_value": None,
                        "opcode": "SSTORE",
                        "namespace": "persistent",
                        "pc": 2,
                        "depth": 2,
                        "index": 8,
                        "frame_id": 1,
                    }
                ],
                "sha3s": [],
                "frames": [
                    {
                        "id": 0,
                        "parent_id": None,
                        "type": "ROOT",
                        "depth": 1,
                        "storage_address": ADDRESS_A,
                        "requested_code_address": ADDRESS_A,
                        "code_address": CODE_A,
                        "code_attribution": "exact",
                        "code_source": "eip7702",
                        "code_designator": "0xef0100" + "aa" * 20,
                        "target_confirmed": True,
                        "faulted": False,
                        "exit_error": None,
                        "outcome": "succeeded",
                        "completion_validated": True,
                        "completion_word": None,
                    },
                    {
                        "id": 1,
                        "parent_id": 0,
                        "type": "CALL",
                        "depth": 2,
                        "storage_address": ADDRESS_B,
                        "requested_code_address": ADDRESS_B,
                        "code_address": CODE_B,
                        "code_attribution": "exact",
                        "code_source": "eip7702",
                        "code_designator": "0xef0100" + "bb" * 20,
                        "target_confirmed": True,
                        "faulted": False,
                        "exit_error": None,
                        "outcome": "succeeded",
                        "completion_validated": True,
                        "completion_word": ONE,
                    },
                ],
                "stepCount": 10,
                "lastOp": "STOP",
                "lastDepth": 1,
            }
        }


class _PrestateProvider:
    def __init__(self, result):
        self.result = result

    async def make_request(self, chain_id, method, params):
        return {"result": self.result}


class _HistoryService(TransactionHistoryService):
    async def _resolve_metadata(
        self,
        chain_id,
        address,
        block_number,
        *,
        follow_proxy=True,
        follow_delegation=True,
    ):
        if hasattr(self, "delegation_calls"):
            self.delegation_calls.append((address.lower(), follow_delegation))
        if hasattr(self, "resolution_calls"):
            self.resolution_calls.append((chain_id, address, block_number, follow_proxy))
        if address.lower() == ADDRESS_B:
            raise RuntimeError("unverified fixture")
        return ContractMetadata(
            chain_id=chain_id,
            address=address,
            name="Proxy A",
            is_proxy=True,
            implementation_address=CODE_A,
        )


class _CountingHistoryService(TransactionHistoryService):
    async def _resolve_metadata(
        self,
        chain_id,
        address,
        block_number,
        *,
        follow_proxy=True,
        follow_delegation=True,
    ):
        self.resolution_calls.append((address.lower(), follow_proxy))
        key = (address.lower(), follow_proxy)
        attempts = self.attempts.get(key, 0)
        self.attempts[key] = attempts + 1
        if getattr(self, "always_timeout", False):
            raise asyncio.TimeoutError
        if self.fail_first and attempts == 0:
            raise RuntimeError("temporary provider failure")
        return ContractMetadata(
            chain_id=chain_id,
            address=address,
            name="ResolvedContract",
            is_verified=True,
            is_proxy=False,
        )


class TransactionOwnerTests(TestCase):
    def setUp(self):
        self.tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=100),
            TypeDecoder(),
        )

    def test_persistent_owners_include_restored_noop_and_reverted_histories(self):
        self.assertEqual(
            self.tracer.persistent_storage_owners(artifact()),
            (ADDRESS_A, ADDRESS_B),
        )

    def test_slot_classifications_keep_forensic_histories(self):
        value = artifact()
        restored = self.tracer.project_trace_artifact(value, ADDRESS_A)
        reverted = self.tracer.project_trace_artifact(value, ADDRESS_B)

        restored_slots = _group_changes_by_slot(
            restored.changes,
            storage_address=ADDRESS_A.upper().replace("0X", "0x"),
        )
        reverted_slots = _group_changes_by_slot(reverted.changes, storage_address=ADDRESS_B)

        self.assertEqual(restored_slots[0].classification, "restored")
        self.assertEqual(restored_slots[0].event_count, 3)
        self.assertEqual(restored_slots[0].changes[-1].effect, "noop")
        self.assertFalse(restored_slots[0].changes[-1].changed_value)
        self.assertEqual(
            restored_slots[0].changes[0].storage_address,
            ADDRESS_A,
        )
        self.assertEqual(reverted_slots[0].classification, "reverted_only")
        self.assertEqual(reverted_slots[0].changes[0].frame_outcome, "reverted")

    def test_each_delegate_code_uses_its_own_layout(self):
        slot_two = "0x" + "00" * 31 + "02"
        value = replace(
            artifact(),
            prestate_diff={
                "pre": {ADDRESS_A: {"storage": {SLOT_1: ZERO, slot_two: ZERO}}},
                "post": {ADDRESS_A: {"storage": {SLOT_1: ONE, slot_two: ONE}}},
            },
            write_events=[
                {
                    **artifact().write_events[0],
                    "slot": SLOT_1,
                    "code_address": CODE_A,
                    "index": 10,
                },
                {
                    **artifact().write_events[0],
                    "slot": slot_two,
                    "code_address": CODE_B,
                    "index": 20,
                },
            ],
        )
        uint_type = StorageType(
            "t_compiler_local", "uint256", "value", "inplace", 32
        )
        address_type = StorageType(
            "t_compiler_local", "address", "value", "inplace", 20
        )

        def layout(name, slot, value_type):
            return StorageLayout(
                name,
                [
                    StorageVariable(
                        name,
                        slot,
                        0,
                        value_type.num_bytes,
                        value_type.id,
                        value_type.label,
                    )
                ],
                {value_type.id: value_type},
            )

        diff = self.tracer.project_trace_artifact(
            value,
            ADDRESS_A,
            layouts_by_code_address={
                CODE_A: layout("ownerNonce", 1, uint_type),
                CODE_B: layout("strategyOwner", 2, address_type),
            },
        )

        self.assertEqual(
            [change.variable_path for change in diff.changes],
            ["ownerNonce", "strategyOwner"],
        )
        self.assertEqual(
            [change.new_decoded.type_label for change in diff.changes],
            ["uint256", "address"],
        )

    def test_exact_trace_code_name_precedes_generic_or_stale_proxy_names(self):
        self.assertEqual(
            TransactionHistoryService._preferred_name(
                ["OssifiableProxy", "WithdrawalQueueERC721", "VaultHub"]
            ),
            "WithdrawalQueueERC721",
        )
        self.assertTrue(
            TransactionHistoryService._names_match("Yearn V3 Vault", "YearnV3Vault")
        )
        self.assertFalse(
            TransactionHistoryService._names_match("VaultHub", "WithdrawalQueueERC721")
        )


class Eip7702TraceTests(IsolatedAsyncioTestCase):
    async def test_code_capability_requires_complete_exact_trace_evidence(self):
        cases = (
            ("exact", 10, True),
            ("inferred", 10, False),
            ("exact", 0, False),
        )
        for attribution, step_count, expected in cases:
            with self.subTest(
                attribution=attribution,
                step_count=step_count,
            ):
                tracer = TransactionAnalysisService(
                    _NoopProvider(),
                    Settings(MAX_SSTORE_OPS=1),
                    TypeDecoder(),
                )
                write = dict(artifact().write_events[0])
                write["code_attribution"] = attribution
                tracer.trace_extractor.extract = AsyncMock(
                    return_value=TransactionTraceEvidence(
                        receipt={
                            "blockNumber": artifact().block_number,
                            "status": 1,
                            "from": artifact().transaction_from,
                            "to": artifact().transaction_to,
                            "contractAddress": None,
                        },
                        prestate_diff={"pre": {}, "post": {}},
                        writes=[write],
                        sha3_operations=[],
                        evm_step_count=step_count,
                    )
                )

                traced = await tracer.load_trace_artifact(
                    1,
                    artifact().tx_hash,
                )

                self.assertEqual(
                    traced.capabilities["code_attribution_complete"],
                    expected,
                )

    async def test_compact_trace_preserves_exact_effective_code_output(self):
        provider = _CompactTraceProvider()
        client = TraceRPCClient(
            provider,
            Settings(
                MAX_SSTORE_OPS=2,
                MAX_TRACE_STEPS=10,
                MAX_TRACE_SHA3_OPS=1,
            ),
        )

        result = await client._execute_compact_storage_trace(
            1,
            "0x" + "ab" * 32,
        )

        self.assertIsNotNone(result)
        writes, _, step_count = result
        self.assertEqual(step_count, 10)
        self.assertEqual(writes[0]["address"], ADDRESS_A)
        self.assertEqual(writes[0]["code_address"], CODE_A)
        self.assertEqual(writes[0]["code_attribution"], "exact")
        self.assertEqual(writes[1]["address"], ADDRESS_B)
        self.assertEqual(writes[1]["code_address"], CODE_B)
        self.assertEqual(writes[1]["code_attribution"], "exact")
        tracer_source = provider.params[1]["tracer"]
        self.assertIn("db.getCode(requestedHex)", tracer_source)
        self.assertIn("rawCode.length === 48", tracer_source)
        self.assertIn("rawCode.slice(0, 8) === '0xef0100'", tracer_source)
        self.assertNotIn("pendingCalls", tracer_source)
        self.assertNotIn("toAddress(log.stack.peek(1))", tracer_source)
        self.assertIn("enter: function(call)", tracer_source)
        self.assertIn("exit: function(result)", tracer_source)
        self.assertIn("pendingCompletions", tracer_source)
        self.assertIn("if (this.fatal === null)", tracer_source)
        self.assertIn("this.steps >= 10", tracer_source)
        self.assertIn("this.writes.length >= 2", tracer_source)
        self.assertIn("this.sha3s.length >= 1", tracer_source)

    async def test_compact_trace_rejects_the_first_write_above_the_limit(self):
        client = TraceRPCClient(
            _CompactTraceProvider(),
            Settings(MAX_SSTORE_OPS=1),
        )

        with self.assertRaises(TraceNotAvailableError):
            await client._execute_compact_storage_trace(
                1,
                "0x" + "ab" * 32,
            )

    async def test_public_trace_degrades_when_compact_trace_reaches_a_limit(self):
        client = TraceRPCClient(
            _CompactTraceProvider(),
            Settings(MAX_SSTORE_OPS=1),
        )

        writes, sha3s, step_count, degraded_reason = (
            await client.execute_structlogs_trace(
                1,
                "0x" + "ab" * 32,
            )
        )

        self.assertEqual(writes, [])
        self.assertEqual(sha3s, [])
        self.assertEqual(step_count, 0)
        self.assertEqual(degraded_reason, "trace_limit")

    async def test_prestate_trace_rejects_oversized_storage_before_normalization(self):
        client = TraceRPCClient(
            _PrestateProvider(
                {
                    "pre": {
                        ADDRESS_A: {
                            "storage": {
                                SLOT_1: ONE,
                                ZERO: ONE,
                            }
                        }
                    },
                    "post": {},
                }
            ),
            Settings(MAX_PRESTATE_STORAGE_ENTRIES=1),
        )

        with self.assertRaises(TraceNotAvailableError):
            await client.execute_prestate_trace(1, artifact().tx_hash)

    def test_incomplete_code_attribution_keeps_raw_writes_without_layout(self):
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=100),
            TypeDecoder(),
        )
        value_type = StorageType(
            "t_uint256",
            "uint256",
            "value",
            "inplace",
            32,
        )
        layout = StorageLayout(
            "EndBlockDelegate",
            [
                StorageVariable(
                    "wrongLayout",
                    1,
                    0,
                    32,
                    value_type.id,
                    value_type.label,
                )
            ],
            {value_type.id: value_type},
        )
        raw_artifact = replace(
            artifact(),
            capabilities={
                **artifact().capabilities,
                "code_attribution_complete": False,
            },
        )

        diff = tracer.project_trace_artifact(
            raw_artifact,
            ADDRESS_A,
            layout=layout,
            layouts_by_code_address={CODE_A: layout},
        )

        self.assertFalse(diff.is_complete)
        self.assertIsNone(diff.layout)
        self.assertTrue(diff.changes)
        self.assertTrue(all(change.variable is None for change in diff.changes))

    def test_transaction_time_code_layout_wins_over_end_block_delegate_layout(self):
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=100),
            TypeDecoder(),
        )
        value_type = StorageType(
            "t_uint256",
            "uint256",
            "value",
            "inplace",
            32,
        )

        def layout(name):
            return StorageLayout(
                name,
                [
                    StorageVariable(
                        name,
                        1,
                        0,
                        32,
                        value_type.id,
                        value_type.label,
                    )
                ],
                {value_type.id: value_type},
            )

        diff = tracer.project_trace_artifact(
            artifact(),
            ADDRESS_A,
            layout=layout("endBlockDelegate"),
            layouts_by_code_address={
                CODE_A: layout("transactionTimeDelegate"),
            },
        )

        self.assertEqual(
            [change.variable_path for change in diff.changes],
            [
                "transactionTimeDelegate",
                "transactionTimeDelegate",
                "transactionTimeDelegate",
            ],
        )

    async def test_transaction_response_is_incomplete_without_exact_code_attribution(
        self,
    ):
        raw_artifact = replace(
            artifact(),
            capabilities={
                **artifact().capabilities,
                "code_attribution_complete": False,
            },
        )
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=100),
            TypeDecoder(),
            trace_cache_repo=_CachedArtifactRepository(raw_artifact),
        )
        service = _HistoryService(
            tracer=tracer,
            web3_provider=_NoopProvider(),
            settings=tracer.settings,
            layout_parser=None,
            verification_service=object(),
        )

        response = await get_transaction_storage_history(
            chain_id=1,
            tx_hash=raw_artifact.tx_hash,
            history_service=service,
        )

        self.assertFalse(response.capabilities.code_attribution_complete)
        self.assertFalse(response.is_complete)
        self.assertTrue(
            all(not contract.layout_available for contract in response.contracts)
        )

    async def test_exact_trace_target_is_resolved_without_a_second_hop(self):
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=100),
            TypeDecoder(),
            trace_cache_repo=_CachedArtifactRepository(artifact()),
        )
        service = _HistoryService(
            tracer=tracer,
            web3_provider=_NoopProvider(),
            settings=tracer.settings,
            layout_parser=None,
            verification_service=object(),
        )
        service.delegation_calls = []

        result = await service.analyze(
            1,
            artifact().tx_hash,
            storage_addresses=(ADDRESS_A,),
        )

        self.assertEqual(result.contracts[0].code_addresses, (CODE_A,))
        self.assertIn((ADDRESS_A, True), service.delegation_calls)
        self.assertIn((CODE_A, False), service.delegation_calls)

class PrestateRecoveryTests(TestCase):
    def test_unchanged_observed_slots_are_preserved_as_evidence(self):
        slot_two = "0x" + "00" * 31 + "02"
        diff = {"pre": {}, "post": {}}

        TransactionTraceExtractor._merge_observed_prestate(
            diff,
            {ADDRESS_A: {"storage": {SLOT_1: FIVE, slot_two: SIX}}},
            {(ADDRESS_A, SLOT_1)},
        )

        self.assertEqual(diff["pre"][ADDRESS_A]["storage"][slot_two], SIX)
        self.assertEqual(diff["post"][ADDRESS_A]["storage"][slot_two], SIX)

    def test_full_prestate_account_is_normalized_once(self):
        class CountingStorage(dict):
            def __init__(self, values):
                super().__init__(values)
                self.items_calls = 0

            def items(self):
                self.items_calls += 1
                return super().items()

        slot_two = "0x" + "00" * 31 + "02"
        storage = CountingStorage({SLOT_1: FIVE, slot_two: SIX})
        diff = {"pre": {}, "post": {}}

        TransactionTraceExtractor._merge_observed_prestate(
            diff,
            {ADDRESS_A: {"storage": storage}},
            {(ADDRESS_A, SLOT_1), (ADDRESS_A, slot_two)},
        )

        self.assertEqual(storage.items_calls, 1)
        self.assertEqual(diff["pre"][ADDRESS_A]["storage"][SLOT_1], FIVE)
        self.assertEqual(diff["pre"][ADDRESS_A]["storage"][slot_two], SIX)

    def test_post_only_net_change_is_not_overwritten_by_initial_value(self):
        diff = {
            "pre": {},
            "post": {ADDRESS_A: {"storage": {SLOT_1: ONE}}},
        }
        TransactionTraceExtractor._normalize_diff(diff)
        TransactionTraceExtractor._merge_observed_prestate(
            diff,
            {ADDRESS_A: {"storage": {}}},
            {(ADDRESS_A, SLOT_1)},
        )

        self.assertEqual(diff["pre"][ADDRESS_A]["storage"][SLOT_1], ZERO)
        self.assertEqual(diff["post"][ADDRESS_A]["storage"][SLOT_1], ONE)

    def test_diff_omission_marks_observed_slot_as_restored(self):
        diff = {"pre": {}, "post": {}}
        TransactionTraceExtractor._merge_observed_prestate(
            diff,
            {ADDRESS_A: {"storage": {SLOT_1: FIVE}}},
            {(ADDRESS_A, SLOT_1)},
        )

        self.assertEqual(diff["pre"][ADDRESS_A]["storage"][SLOT_1], FIVE)
        self.assertEqual(diff["post"][ADDRESS_A]["storage"][SLOT_1], FIVE)


class TransactionHistoryServiceTests(IsolatedAsyncioTestCase):
    async def test_multiple_resolution_targets_are_not_rejected_by_count(self):
        one_owner = replace(
            artifact(),
            write_events=[
                event
                for event in artifact().write_events
                if event["address"] == ADDRESS_A
            ],
        )
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(
                MAX_SSTORE_OPS=100,
                MAX_PARALLEL_CONTRACT_RESOLUTIONS=1,
            ),
            TypeDecoder(),
            trace_cache_repo=_CachedArtifactRepository(one_owner),
        )
        service = _HistoryService(
            tracer=tracer,
            web3_provider=_NoopProvider(),
            settings=tracer.settings,
            layout_parser=None,
            verification_service=object(),
        )
        service.resolution_calls = []

        result = await service.analyze(1, one_owner.tx_hash)

        self.assertEqual(len(result.contracts), 1)
        self.assertEqual(
            service.resolution_calls,
            [
                (1, ADDRESS_A, one_owner.block_number, True),
                (1, CODE_A, one_owner.block_number, False),
            ],
        )

    async def test_expired_resolution_budget_keeps_raw_owners(self):
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(
                MAX_SSTORE_OPS=100,
                TRANSACTION_RESOLUTION_BUDGET_SECONDS=0,
            ),
            TypeDecoder(),
            trace_cache_repo=_CachedArtifactRepository(artifact()),
        )
        service = _HistoryService(
            tracer=tracer,
            web3_provider=_NoopProvider(),
            settings=tracer.settings,
            layout_parser=None,
            verification_service=object(),
        )
        service.resolution_calls = []

        result = await service.analyze(1, artifact().tx_hash)

        self.assertEqual(len(result.contracts), 2)
        self.assertEqual(
            [contract.resolution_status for contract in result.contracts],
            ["not_resolved", "not_resolved"],
        )
        self.assertEqual(service.resolution_calls, [])

    async def test_concurrent_cold_trace_requests_share_one_extraction(self):
        repository = _SharedArtifactRepository()
        single_flight = TraceSingleFlight()
        extraction_count = 0

        async def extract(chain_id, tx_hash):
            nonlocal extraction_count
            extraction_count += 1
            await asyncio.sleep(0.01)
            return TransactionTraceEvidence(
                receipt={
                    "blockNumber": artifact().block_number,
                    "status": 1,
                },
                prestate_diff={"pre": {}, "post": {}},
                writes=[],
                sha3_operations=[],
                evm_step_count=1,
            )

        services = []
        for _ in range(12):
            tracer = TransactionAnalysisService(
                _NoopProvider(),
                Settings(),
                TypeDecoder(),
                trace_cache_repo=repository,
                single_flight=single_flight,
            )
            tracer.trace_extractor.extract = extract
            services.append(tracer)

        results = await asyncio.gather(
            *(
                service.load_trace_artifact(1, artifact().tx_hash)
                for service in services
            )
        )

        self.assertEqual(extraction_count, 1)
        self.assertEqual(repository.save_count, 1)
        self.assertTrue(all(result is repository.value for result in results))
        self.assertEqual(single_flight._entries, {})

    async def test_cancelled_trace_waiter_does_not_leak_its_lock_entry(self):
        single_flight = TraceSingleFlight()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def hold():
            async with single_flight.hold(1, artifact().tx_hash):
                entered.set()
                await release.wait()

        leader = asyncio.create_task(hold())
        await entered.wait()
        waiter = asyncio.create_task(hold())
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        release.set()
        await leader

        self.assertEqual(single_flight._entries, {})

    async def test_trace_limit_preserves_bounded_net_state(self):
        repository = SimpleNamespace(
            get=AsyncMock(return_value=None),
            save=AsyncMock(),
        )
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=1),
            TypeDecoder(),
            trace_cache_repo=repository,
        )
        tracer.trace_extractor.extract = AsyncMock(
            return_value=TransactionTraceEvidence(
                receipt={
                    "blockNumber": artifact().block_number,
                    "status": 1,
                },
                prestate_diff={
                    "pre": {
                        ADDRESS_A: {
                            "storage": {SLOT_1: ZERO},
                        }
                    },
                    "post": {
                        ADDRESS_A: {
                            "storage": {SLOT_1: ONE},
                        }
                    },
                },
                writes=artifact().write_events[:2],
                sha3_operations=[],
                evm_step_count=10,
            )
        )

        traced = await tracer.load_trace_artifact(1, artifact().tx_hash)

        self.assertEqual(traced.write_events, [])
        self.assertEqual(traced.prestate_diff["post"][ADDRESS_A]["storage"], {
            SLOT_1: ONE,
        })
        self.assertEqual(traced.capabilities["degraded_reason"], "trace_limit")
        self.assertFalse(traced.capabilities["write_history_complete"])
        self.assertEqual(
            tracer.persistent_storage_owners(traced),
            (ADDRESS_A,),
        )
        repository.save.assert_not_awaited()

    async def test_transaction_api_discloses_degraded_net_state(self):
        degraded = replace(
            artifact(),
            write_events=[],
            prestate_diff={
                "pre": {
                    ADDRESS_A: {
                        "storage": {SLOT_1: ZERO},
                    }
                },
                "post": {
                    ADDRESS_A: {
                        "storage": {SLOT_1: ONE},
                    }
                },
            },
            capabilities={
                "write_history_complete": False,
                "address_attribution_complete": True,
                "code_attribution_complete": False,
                "degraded_reason": "trace_limit",
            },
            trace_step_count=None,
        )
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=100),
            TypeDecoder(),
            trace_cache_repo=_CachedArtifactRepository(degraded),
        )
        service = _HistoryService(
            tracer=tracer,
            web3_provider=_NoopProvider(),
            settings=tracer.settings,
            layout_parser=None,
            verification_service=object(),
        )

        response = await get_transaction_storage_history(
            chain_id=1,
            tx_hash=degraded.tx_hash,
            history_service=service,
        )

        self.assertFalse(response.trace_unavailable)
        self.assertEqual(response.degraded_reason, "trace_limit")
        self.assertFalse(response.is_complete)
        self.assertEqual(response.summary.storage_owners, 1)
        self.assertEqual(response.summary.slots_written, 1)
        self.assertEqual(response.contracts[0].slots[0].slot, SLOT_1)

    async def test_transaction_api_redacts_upstream_rpc_error_details(self):
        with self.assertRaises(HTTPException) as raised:
            await get_transaction_storage_history(
                chain_id=1,
                tx_hash=artifact().tx_hash,
                history_service=_FailingHistoryService(),
            )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(
            raised.exception.detail,
            {
                "error": "Upstream RPC request failed",
                "code": "RPC_ERROR",
            },
        )
        self.assertNotIn("secret", str(raised.exception.detail))
        self.assertNotIn("token", str(raised.exception.detail))

    async def test_proxy_self_code_uses_only_its_direct_layout(self):
        value_type = StorageType(
            "t_uint256",
            "uint256",
            "value",
            "inplace",
            32,
        )

        def layout(name, slot):
            return StorageLayout(
                name,
                [
                    StorageVariable(
                        name,
                        slot,
                        0,
                        32,
                        value_type.id,
                        value_type.label,
                    )
                ],
                {value_type.id: value_type},
            )

        class ProxyHistoryService(TransactionHistoryService):
            async def _resolve_metadata(
                self,
                chain_id,
                address,
                block_number,
                *,
                follow_proxy=True,
                follow_delegation=True,
            ):
                return ContractMetadata(
                    chain_id=chain_id,
                    address=address,
                    name="Implementation" if follow_proxy else "Proxy",
                    is_verified=True,
                    is_proxy=follow_proxy,
                    implementation_address=CODE_A if follow_proxy else None,
                    storage_layout=(
                        layout("implementationValue", 1)
                        if follow_proxy
                        else layout("proxyValue", 2)
                    ),
                )

        self_attributed = replace(
            artifact(),
            write_events=[
                {
                    **event,
                    "code_address": ADDRESS_A,
                }
                for event in artifact().write_events
            ],
        )
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=100),
            TypeDecoder(),
            trace_cache_repo=_CachedArtifactRepository(self_attributed),
        )
        service = ProxyHistoryService(
            tracer=tracer,
            web3_provider=_NoopProvider(),
            settings=tracer.settings,
            layout_parser=None,
            verification_service=object(),
        )

        result = await service.analyze(
            1,
            self_attributed.tx_hash,
            storage_addresses=(ADDRESS_A,),
        )

        self.assertEqual(
            [change.variable_path for change in result.contracts[0].diff.changes],
            [
                None,
                None,
                None,
            ],
        )
        self.assertEqual(
            list(result.contracts[0].layouts_by_code_address),
            [ADDRESS_A],
        )
        self.assertEqual(
            result.contracts[0].layouts_by_code_address[
                ADDRESS_A
            ].contract_name,
            "proxyValue",
        )

    async def test_non_proxy_self_code_reuses_owner_resolution(self):
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=100),
            TypeDecoder(),
            trace_cache_repo=_CachedArtifactRepository(artifact()),
        )
        service = _CountingHistoryService(
            tracer=tracer,
            web3_provider=_NoopProvider(),
            settings=Settings(CONTRACT_RESOLUTION_RETRY_DELAY_SECONDS=0),
            layout_parser=None,
            verification_service=object(),
        )
        service.resolution_calls = []
        service.attempts = {}
        service.fail_first = False

        result = await service.analyze(
            1,
            artifact().tx_hash,
            storage_addresses=(ADDRESS_B,),
        )

        self.assertEqual(service.resolution_calls, [(ADDRESS_B, True)])
        self.assertEqual(result.contracts[0].resolution_status, "resolved")

    async def test_transient_owner_resolution_is_retried_once(self):
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=100),
            TypeDecoder(),
            trace_cache_repo=_CachedArtifactRepository(artifact()),
        )
        service = _CountingHistoryService(
            tracer=tracer,
            web3_provider=_NoopProvider(),
            settings=Settings(CONTRACT_RESOLUTION_RETRY_DELAY_SECONDS=0),
            layout_parser=None,
            verification_service=object(),
        )
        service.resolution_calls = []
        service.attempts = {}
        service.fail_first = True

        result = await service.analyze(
            1,
            artifact().tx_hash,
            storage_addresses=(ADDRESS_B,),
        )

        self.assertEqual(
            service.resolution_calls,
            [(ADDRESS_B, True), (ADDRESS_B, True)],
        )
        self.assertEqual(result.contracts[0].resolution_status, "resolved")
        self.assertEqual(result.contracts[0].errors, ())

    async def test_repeated_timeout_is_reported_separately_from_source_miss(self):
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=100),
            TypeDecoder(),
            trace_cache_repo=_CachedArtifactRepository(artifact()),
        )
        service = _CountingHistoryService(
            tracer=tracer,
            web3_provider=_NoopProvider(),
            settings=Settings(CONTRACT_RESOLUTION_RETRY_DELAY_SECONDS=0),
            layout_parser=None,
            verification_service=object(),
        )
        service.resolution_calls = []
        service.attempts = {}
        service.fail_first = False
        service.always_timeout = True

        result = await service.analyze(
            1,
            artifact().tx_hash,
            storage_addresses=(ADDRESS_B,),
        )

        self.assertEqual(
            service.resolution_calls,
            [(ADDRESS_B, True), (ADDRESS_B, True)],
        )
        self.assertEqual(result.contracts[0].resolution_status, "timed_out")
        self.assertEqual(
            result.contracts[0].errors,
            (f"{ADDRESS_B}: TimeoutError: historical resolution failed",),
        )

    async def test_historical_resolution_uses_full_verification_fallback(self):
        service = TransactionHistoryService(
            tracer=None,
            web3_provider=_NoopProvider(),
            settings=Settings(),
            layout_parser=None,
            verification_service=object(),
        )
        expected = ContractMetadata(chain_id=1, address=ADDRESS_A)
        resolver = SimpleNamespace(resolve=AsyncMock(return_value=expected))
        session_context = AsyncMock()
        session_context.__aenter__.return_value = object()

        with (
            patch(
                "app.services.transaction_history.async_session_factory",
                return_value=session_context,
            ),
            patch(
                "app.services.transaction_history.ContractResolver",
                return_value=resolver,
            ),
        ):
            result = await service._resolve_metadata(
                1,
                ADDRESS_A,
                artifact().block_number,
                follow_proxy=False,
            )

        self.assertIs(result, expected)
        resolver.resolve.assert_awaited_once_with(
            1,
            ADDRESS_A,
            block_number=artifact().block_number,
            follow_proxy=False,
            follow_delegation=True,
        )

    async def test_shared_artifact_is_loaded_once_and_resolution_degrades_locally(self):
        repository = _CachedArtifactRepository(artifact())
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=100, MAX_PARALLEL_CONTRACT_RESOLUTIONS=2),
            TypeDecoder(),
            trace_cache_repo=repository,
        )
        tracer.trace_extractor.extract = AsyncMock(
            side_effect=AssertionError("cached artifact must prevent retracing")
        )
        service = _HistoryService(
            tracer=tracer,
            web3_provider=_NoopProvider(),
            settings=tracer.settings,
            layout_parser=None,
            verification_service=object(),
        )
        service.resolution_calls = []

        result = await service.analyze(1, artifact().tx_hash)

        self.assertEqual(repository.get_count, 1)
        self.assertEqual(
            [contract.storage_address for contract in result.contracts],
            [ADDRESS_A, ADDRESS_B],
        )
        self.assertEqual(result.contracts[0].code_addresses, (CODE_A,))
        self.assertEqual(result.contracts[1].metadata, None)
        self.assertEqual(
            result.contracts[1].errors,
            (
                f"{ADDRESS_B}: RuntimeError: historical resolution failed",
            ),
        )
        self.assertEqual(
            {block for _, _, block, _ in service.resolution_calls},
            {artifact().block_number},
        )

    async def test_transaction_only_api_groups_contracts_and_references_global_order(self):
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=100, MAX_PARALLEL_CONTRACT_RESOLUTIONS=2),
            TypeDecoder(),
            trace_cache_repo=_CachedArtifactRepository(artifact()),
        )
        service = _HistoryService(
            tracer=tracer,
            web3_provider=_NoopProvider(),
            settings=tracer.settings,
            layout_parser=None,
            verification_service=object(),
        )

        response = await get_transaction_storage_history(
            chain_id=1,
            tx_hash=artifact().tx_hash,
            include_global_order=True,
            history_service=service,
        )

        self.assertEqual(response.summary.storage_owners, 2)
        self.assertEqual(response.summary.slots_written, 2)
        self.assertEqual(response.summary.sstore_events, 4)
        self.assertEqual(response.summary.restored_slots, 1)
        self.assertEqual(response.summary.reverted_only_slots, 1)
        self.assertEqual(response.summary.reverted_writes, 1)
        self.assertEqual(response.summary.noop_writes, 1)
        self.assertEqual(
            [reference.step for reference in response.global_order],
            [10, 15, 20, 30],
        )
        self.assertEqual(
            response.contracts[0].slots[0].classification,
            "restored",
        )
        self.assertEqual(
            response.contracts[1].slots[0].classification,
            "reverted_only",
        )
        self.assertEqual(response.contracts[1].resolution_status, "failed")

        without_timeline = await get_transaction_storage_history(
            chain_id=1,
            tx_hash=artifact().tx_hash,
            include_global_order=False,
            history_service=service,
        )
        self.assertIsNone(without_timeline.global_order)

    async def test_reverted_root_retains_attempted_writes_without_net_effects(self):
        reverted_artifact = replace(artifact(), root_succeeded=False)
        tracer = TransactionAnalysisService(
            _NoopProvider(),
            Settings(MAX_SSTORE_OPS=100),
            TypeDecoder(),
            trace_cache_repo=_CachedArtifactRepository(reverted_artifact),
        )
        service = _HistoryService(
            tracer=tracer,
            web3_provider=_NoopProvider(),
            settings=tracer.settings,
            layout_parser=None,
            verification_service=object(),
        )

        response = await get_transaction_storage_history(
            chain_id=1,
            tx_hash=reverted_artifact.tx_hash,
            include_global_order=True,
            history_service=service,
        )

        self.assertEqual(response.status, "reverted")
        self.assertEqual(response.summary.sstore_events, 4)
        self.assertEqual(response.summary.reverted_writes, 4)
        self.assertEqual(response.summary.net_changed_slots, 0)
        self.assertTrue(
            all(
                slot.classification == "reverted_only"
                for contract in response.contracts
                for slot in contract.slots
            )
        )
