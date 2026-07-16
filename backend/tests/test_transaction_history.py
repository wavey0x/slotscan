import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from app.api.routes.transactions import (
    _group_changes_by_slot,
    get_tx_diff,
    get_transaction_storage_history,
)
from app.config import Settings
from app.models.domain import (
    ContractMetadata,
    StorageLayout,
    StorageType,
    StorageVariable,
)
from app.repositories.trace_cache import TransactionTraceArtifactData
from app.services.decoder import TypeDecoder
from app.services.tracer.tracer import TransactionAnalysisService
from app.services.tracer.extractor import TransactionTraceExtractor
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


class _HistoryService(TransactionHistoryService):
    async def _resolve_metadata(
        self,
        chain_id,
        address,
        block_number,
        *,
        follow_proxy=True,
    ):
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
            "t_uint256", "uint256", "value", "inplace", 32
        )

        def layout(name, slot):
            return StorageLayout(
                name,
                [StorageVariable(name, slot, 0, 32, uint_type.id, uint_type.label)],
                {uint_type.id: uint_type},
            )

        diff = self.tracer.project_trace_artifact(
            value,
            ADDRESS_A,
            layouts_by_code_address={
                CODE_A: layout("ownerNonce", 1),
                CODE_B: layout("strategyDebt", 2),
            },
        )

        self.assertEqual(
            [change.variable_path for change in diff.changes],
            ["ownerNonce", "strategyDebt"],
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


class PrestateRecoveryTests(TestCase):
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
            http_client=None,
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
            http_client=None,
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
            http_client=None,
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
            http_client=None,
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
            sourcify_layout_only=False,
            follow_proxy=False,
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
            http_client=None,
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
            http_client=None,
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

        single = await get_tx_diff(
            chain_id=1,
            address=ADDRESS_A.upper().replace("0X", "0x"),
            tx_hash=artifact().tx_hash,
            history_service=service,
        )
        self.assertEqual(
            [slot.model_dump() for slot in single.slots],
            [slot.model_dump() for slot in response.contracts[0].slots],
        )

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
            http_client=None,
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
