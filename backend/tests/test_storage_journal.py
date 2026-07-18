import unittest

from app.services.layout_index import StorageNamespace
from app.services.tracer.journal import (
    StorageJournalBuilder,
    WriteEffect,
    ZERO_WORD,
)
from app.services.tracer.rpc_client import TraceRPCClient
from app.config import Settings
from app.repositories.trace_cache import TransactionTraceArtifactData
from app.services.decoder import TypeDecoder
from app.services.tracer.tracer import TransactionAnalysisService
from app.api.routes.transactions import _group_changes_by_slot


ADDRESS = "0x" + "11" * 20
SLOT = "0x" + "00" * 31 + "01"


def word(value: int) -> str:
    return f"0x{value:064x}"


def write(value: int, index: int, **extra):
    return {
        "address": ADDRESS,
        "slot": SLOT,
        "value": word(value),
        "old_value": extra.pop("old_value", None),
        "index": index,
        "pc": index + 100,
        "depth": extra.pop("depth", 1),
        "frame_id": extra.pop("frame_id", 0),
        "frame_reverted": extra.pop("frame_reverted", False),
        "opcode": extra.pop("opcode", "SSTORE"),
        "namespace": extra.pop("namespace", "persistent"),
        **extra,
    }


class StorageJournalTests(unittest.TestCase):
    def setUp(self):
        self.builder = StorageJournalBuilder()

    def test_restored_writes_are_retained_with_truthful_final_state(self):
        writes = [
            write(7, 10, old_value=word(5)),
            write(5, 20, old_value=word(7)),
        ]
        journal = self.builder.build(writes, {"pre": {}, "post": {}}, root_succeeded=True)
        history = journal.for_contract(ADDRESS)[0]
        self.assertEqual([event.step for event in history.writes], [10, 20])
        self.assertEqual(history.initial_value, word(5))
        self.assertEqual(history.final_value, word(5))
        self.assertFalse(history.net_changed)

    def test_reverted_child_write_does_not_mutate_parent_state(self):
        writes = [
            write(9, 10, old_value=word(5), depth=2, frame_id=1, frame_reverted=True),
            write(6, 20, old_value=word(5)),
        ]
        prestate = {
            "pre": {ADDRESS: {"storage": {SLOT: word(5)}}},
            "post": {ADDRESS: {"storage": {SLOT: word(6)}}},
        }
        history = self.builder.build(writes, prestate, root_succeeded=True).histories[0]
        self.assertEqual(history.writes[0].effect, WriteEffect.REVERTED)
        self.assertEqual(history.writes[1].effect, WriteEffect.APPLIED)
        self.assertEqual(history.final_value, word(6))

    def test_reverted_frame_replays_its_own_intermediate_values(self):
        writes = [
            write(
                9,
                10,
                depth=2,
                frame_id=1,
                frame_reverted=True,
                rollback_frame_id=1,
            ),
            write(
                10,
                11,
                depth=2,
                frame_id=1,
                frame_reverted=True,
                rollback_frame_id=1,
            ),
            write(6, 20),
        ]
        prestate = {
            "pre": {ADDRESS: {"storage": {SLOT: word(5)}}},
            "post": {ADDRESS: {"storage": {SLOT: word(6)}}},
        }

        history = self.builder.build(writes, prestate, root_succeeded=True).histories[0]

        self.assertEqual(
            [event.value_before for event in history.writes],
            [word(5), word(9), word(5)],
        )
        self.assertEqual(
            [event.frame_outcome for event in history.writes],
            ["reverted", "reverted", "applied"],
        )

    def test_root_failure_reverts_every_write(self):
        history = self.builder.build(
            [write(9, 1, old_value=word(5))],
            {"pre": {}, "post": {}},
            root_succeeded=False,
        ).histories[0]
        self.assertEqual(history.writes[0].effect, WriteEffect.REVERTED)
        self.assertEqual(history.initial_value, word(5))
        self.assertEqual(history.final_value, word(5))

    def test_noop_write_is_visible(self):
        history = self.builder.build(
            [write(5, 1, old_value=word(5))],
            {"pre": {}, "post": {}},
            root_succeeded=True,
        ).histories[0]
        self.assertEqual(history.writes[0].effect, WriteEffect.NOOP)
        self.assertEqual(len(history.writes), 1)

    def test_unknown_old_value_remains_visible_and_marks_capability_incomplete(self):
        raw_write = write(8, 1)
        journal = self.builder.build(
            [raw_write],
            {"pre": {}, "post": {}},
            root_succeeded=True,
        )
        self.assertIsNone(journal.events[0].value_before)
        self.assertFalse(journal.capabilities.write_old_values)

    def test_final_state_mismatch_downgrades_replay_capabilities(self):
        journal = self.builder.build(
            [write(6, 1, old_value=word(5))],
            {
                "pre": {ADDRESS: {"storage": {SLOT: word(5)}}},
                "post": {ADDRESS: {"storage": {SLOT: word(7)}}},
            },
            root_succeeded=True,
        )

        self.assertFalse(journal.capabilities.state_reconciliation)
        self.assertFalse(journal.capabilities.frame_outcomes)
        self.assertFalse(journal.capabilities.write_old_values)
        self.assertFalse(journal.capabilities.final_state_values)

    def test_transient_slot_zero_is_separate_and_clears_after_transaction(self):
        transient = write(
            3,
            1,
            old_value=ZERO_WORD,
            opcode="TSTORE",
            namespace="transient",
        )
        journal = self.builder.build([transient], {"pre": {}, "post": {}}, root_succeeded=True)
        history = journal.for_contract(ADDRESS, StorageNamespace.TRANSIENT)[0]
        self.assertEqual(history.namespace, StorageNamespace.TRANSIENT)
        self.assertEqual(history.initial_value, ZERO_WORD)
        self.assertEqual(history.final_value, ZERO_WORD)
        self.assertTrue(journal.capabilities.transient_storage)

    def test_cached_trace_addresses_are_left_padded_to_twenty_bytes(self):
        unpadded_yfi = "0xbc529c00c6401aef6d220be8c6ea1667f6ad93e"
        canonical_yfi = "0x0bc529c00c6401aef6d220be8c6ea1667f6ad93e"
        raw_write = write(
            6,
            1,
            old_value=word(5),
            address=unpadded_yfi,
            code_address=unpadded_yfi,
        )

        journal = self.builder.build(
            [raw_write],
            {
                "pre": {canonical_yfi: {"storage": {SLOT: word(5)}}},
                "post": {canonical_yfi: {"storage": {SLOT: word(6)}}},
            },
            root_succeeded=True,
        )

        self.assertEqual(journal.events[0].address, canonical_yfi)
        self.assertEqual(journal.events[0].code_address, canonical_yfi)


class FrameOutcomeTests(unittest.TestCase):
    def test_rpc_trace_normalizes_segmented_preimages_and_memory_words(self):
        client = TraceRPCClient(object())

        self.assertEqual(
            client._normalize_preimage("0x1122" + "0x3344"),
            "0x11223344",
        )
        self.assertEqual(
            client._extract_memory_slice(
                ["0x" + "11" * 32, "0x" + "22" * 32],
                31,
                2,
            ),
            "0x1122",
        )
        self.assertEqual(
            client._extract_memory_slice(
                ["0x" + "11" * 32],
                10**9,
                2,
            ),
            "0x0000",
        )

    def test_parent_revert_marks_descendant_writes_reverted(self):
        logs = [
            {"depth": 1, "op": "CALL"},
            {"depth": 2, "op": "SSTORE"},
            {"depth": 2, "op": "RETURN"},
            {"depth": 1, "op": "REVERT"},
        ]
        writes = [{"index": 1}]
        TraceRPCClient(object())._annotate_frame_outcomes(logs, writes)
        self.assertEqual(writes[0]["frame_id"], 1)
        self.assertTrue(writes[0]["frame_reverted"])


class _ArtifactRepository:
    def __init__(self, artifact):
        self.artifact = artifact

    async def get(self, chain_id, tx_hash):
        return self.artifact


class TraceArtifactIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_transaction_artifact_projects_truthful_restored_history(self):
        writes = [
            write(7, 10, old_value=word(5)),
            write(5, 20, old_value=word(7)),
        ]
        artifact = TransactionTraceArtifactData(
            chain_id=1,
            tx_hash="0x" + "aa" * 32,
            block_number=100,
            root_succeeded=True,
            write_events=writes,
            prestate_diff={"pre": {}, "post": {}},
            preimage_lookup={},
            capabilities={},
            trace_step_count=200,
        )
        tracer = TransactionAnalysisService(
            object(),
            Settings(),
            TypeDecoder(),
            trace_cache_repo=_ArtifactRepository(artifact),
        )
        cached = await tracer.load_trace_artifact(1, artifact.tx_hash)
        diff = tracer.project_trace_artifact(
            cached,
            ADDRESS,
        )
        self.assertEqual(len(diff.changes), 2)
        self.assertEqual(diff.changes[0].state_initial_value, word(5))
        self.assertEqual(diff.changes[-1].state_final_value, word(5))
        self.assertEqual(diff.trace_step_count, 200)

        grouped = _group_changes_by_slot(diff.changes)
        self.assertEqual(grouped[0].before.value_encoded, word(5))
        self.assertEqual(grouped[0].after.value_encoded, word(5))
        self.assertFalse(grouped[0].net_changed)
        self.assertEqual(len(grouped[0].changes), 2)


if __name__ == "__main__":
    unittest.main()
