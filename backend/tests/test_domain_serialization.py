import unittest

from app.models.domain import (
    DecodedValue,
    SlotValue,
    StorageChange,
    StorageLayout,
    StorageSnapshot,
    TransactionDiff,
)


class DomainSerializationTests(unittest.TestCase):
    def test_layout_round_trip_preserves_vyper_storage_policy(self):
        layout = StorageLayout(
            contract_name="VotingEscrow",
            variables=[],
            types={},
            resolver_version=5,
            language="Vyper",
            compiler_version="0.2.4+commit.7949850",
            storage_scheme="vyper_legacy_hashed",
        )

        self.assertEqual(StorageLayout.from_dict(layout.to_dict()), layout)

    def test_snapshot_round_trip(self):
        snapshot = StorageSnapshot(
            chain_id=1,
            address="0x" + "11" * 20,
            block_number=123,
            slots=[
                SlotValue(
                    slot="0x0",
                    raw_value="0x" + "00" * 32,
                    decoded_value=DecodedValue(
                        raw="0x" + "00" * 32,
                        decoded=0,
                        type_label="uint256",
                    ),
                )
            ],
            is_complete=True,
        )
        self.assertEqual(StorageSnapshot.from_dict(snapshot.to_dict()), snapshot)

    def test_transaction_round_trip_preserves_array_metadata(self):
        diff = TransactionDiff(
            chain_id=1,
            contract_address="0x" + "22" * 20,
            tx_hash="0x" + "33" * 32,
            block_number=456,
            changes=[
                StorageChange(
                    slot="0x1",
                    old_value="0x" + "00" * 32,
                    new_value="0x" + "01".zfill(64),
                    old_decoded=DecodedValue("0x0", 0, "uint32"),
                    new_decoded=DecodedValue("0x1", 1, "uint32"),
                    element_type_id="t_uint32",
                    array_index=7,
                    change_index=9,
                )
            ],
            is_complete=True,
            execution_order_available=True,
        )
        self.assertEqual(TransactionDiff.from_dict(diff.to_dict()), diff)

    def test_legacy_display_property_is_ignored(self):
        value = DecodedValue.from_dict(
            {"raw": "0x0", "decoded": 0, "type_label": "uint256", "display": "0"}
        )
        self.assertEqual(value, DecodedValue("0x0", 0, "uint256"))


if __name__ == "__main__":
    unittest.main()
