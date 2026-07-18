import json
from pathlib import Path
import unittest

from web3 import Web3

from app.api.routes.transactions import _group_changes_by_slot
from app.config import Settings
from app.models.domain import StorageLayout, StorageType, StorageVariable
from app.repositories.trace_cache import TransactionTraceArtifactData
from app.services.decoder import TypeDecoder
from app.services.tracer.rpc_client import TraceRPCClient
from app.services.tracer.tracer import TransactionAnalysisService


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "voting_reth_attribution.json"
)


def voting_layout() -> StorageLayout:
    boolean = StorageType("t_bool", "bool", "value", "inplace", 1)
    uint64 = StorageType("t_uint64", "uint64", "value", "inplace", 8)
    uint256 = StorageType("t_uint256", "uint256", "value", "inplace", 32)
    dynamic_bytes = StorageType("t_bytes", "bytes", "value", "bytes", 32)
    voter_state = StorageType(
        "t_voter_state",
        "VoterState",
        "contract",
        "inplace",
        20,
    )
    voters = StorageType(
        "t_voters",
        "mapping (address => VoterState)",
        "mapping",
        "mapping",
        32,
        key_type="t_address",
        value_type=voter_state.id,
    )
    vote = StorageType(
        "t_vote",
        "struct Vote",
        "struct",
        "inplace",
        224,
        members=[
            StorageVariable("executed", 0, 0, 1, boolean.id, boolean.label),
            StorageVariable("startDate", 0, 1, 8, uint64.id, uint64.label),
            StorageVariable(
                "snapshotBlock",
                0,
                9,
                8,
                uint64.id,
                uint64.label,
            ),
            StorageVariable(
                "supportRequiredPct",
                0,
                17,
                8,
                uint64.id,
                uint64.label,
            ),
            StorageVariable(
                "minAcceptQuorumPct",
                1,
                0,
                8,
                uint64.id,
                uint64.label,
            ),
            StorageVariable("yea", 2, 0, 32, uint256.id, uint256.label),
            StorageVariable("nay", 3, 0, 32, uint256.id, uint256.label),
            StorageVariable(
                "votingPower",
                4,
                0,
                32,
                uint256.id,
                uint256.label,
            ),
            StorageVariable(
                "executionScript",
                5,
                0,
                32,
                dynamic_bytes.id,
                dynamic_bytes.label,
            ),
            StorageVariable("voters", 6, 0, 32, voters.id, voters.label),
        ],
    )
    votes = StorageType(
        "t_votes",
        "mapping (uint256 => Vote)",
        "mapping",
        "mapping",
        32,
        key_type=uint256.id,
        value_type=vote.id,
    )
    types = {
        storage_type.id: storage_type
        for storage_type in (
            boolean,
            uint64,
            uint256,
            dynamic_bytes,
            voter_state,
            voters,
            vote,
            votes,
        )
    }
    return StorageLayout(
        "Voting",
        [
            StorageVariable(
                "votes",
                9,
                0,
                32,
                votes.id,
                votes.label,
            )
        ],
        types,
        language="Solidity",
    )


class VotingRethAttributionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE_PATH.read_text())

    def test_exact_voting_trace_resolves_delegate_mapping_and_packed_member(self):
        fixture = self.fixture
        compact_result = {
            "fatal": None,
            "executable": True,
            "stepCount": fixture["step_count"],
            "hookEnters": fixture["hook_enters"],
            "hookExits": fixture["hook_exits"],
            "frameStack": [0],
            "writes": [fixture["write"]],
            "sha3s": [fixture["sha3"]],
            "frames": fixture["frames"],
            "lastOp": "STOP",
            "lastDepth": 1,
        }
        client = TraceRPCClient(object(), Settings())

        writes, sha3s, step_count = client._decode_compact_trace_result(
            compact_result
        )

        self.assertEqual(len(fixture["transaction_hash"]), 66)
        self.assertEqual(step_count, 167759)
        self.assertEqual(writes[0]["address"], fixture["storage_address"])
        self.assertEqual(
            writes[0]["code_address"],
            fixture["implementation_address"],
        )
        self.assertEqual(writes[0]["slot"], fixture["slot"])
        self.assertEqual(writes[0]["value"], fixture["value_after"])
        self.assertEqual(
            "0x"
            + Web3.keccak(
                bytes.fromhex(fixture["sha3"]["preimage"][2:])
            ).hex(),
            fixture["slot"],
        )
        self.assertEqual(sha3s[0]["preimage"], fixture["sha3"]["preimage"])

        artifact = TransactionTraceArtifactData(
            chain_id=1,
            tx_hash=fixture["transaction_hash"],
            block_number=fixture["block_number"],
            root_succeeded=True,
            transaction_from=None,
            transaction_to=fixture["storage_address"],
            created_contract=None,
            write_events=writes,
            prestate_diff={
                "pre": {
                    fixture["storage_address"]: {
                        "storage": {
                            fixture["slot"]: fixture["value_before"],
                        }
                    }
                },
                "post": {
                    fixture["storage_address"]: {
                        "storage": {
                            fixture["slot"]: fixture["value_after"],
                        }
                    }
                },
            },
            preimage_lookup={
                fixture["slot"]: fixture["sha3"]["preimage"],
            },
            capabilities={
                "write_history_complete": True,
                "address_attribution_complete": True,
                "code_attribution_complete": True,
            },
            trace_step_count=step_count,
        )
        layout = voting_layout()
        service = TransactionAnalysisService(
            object(),
            Settings(),
            TypeDecoder(),
        )

        diff = service.project_trace_artifact(
            artifact,
            fixture["storage_address"],
            layouts_by_code_address={
                fixture["implementation_address"]: layout,
            },
        )

        self.assertTrue(diff.is_complete)
        self.assertEqual(
            [change.variable_path for change in diff.changes],
            [fixture["variable_path"]],
        )
        slots = _group_changes_by_slot(
            diff.changes,
            storage_address=fixture["storage_address"],
            layouts_by_code_address={
                fixture["implementation_address"]: layout,
            },
        )
        executed = next(
            field
            for field in slots[0].packed_fields
            if field.name == fixture["packed_member"]["name"]
        )
        self.assertEqual(
            executed.before.value_decoded,
            fixture["packed_member"]["before"],
        )
        self.assertEqual(
            executed.after.value_decoded,
            fixture["packed_member"]["after"],
        )


if __name__ == "__main__":
    unittest.main()
