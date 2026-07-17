import unittest

from app.models.domain import (
    StorageLayout,
)


class DomainSerializationTests(unittest.TestCase):
    def test_layout_round_trip_preserves_vyper_storage_policy(self):
        layout = StorageLayout(
            contract_name="VotingEscrow",
            variables=[],
            types={},
            language="Vyper",
            compiler_version="0.2.4+commit.7949850",
            storage_scheme="vyper_legacy_hashed",
        )

        self.assertEqual(StorageLayout.from_dict(layout.to_dict()), layout)

if __name__ == "__main__":
    unittest.main()
