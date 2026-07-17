import unittest

from app.models.domain import (
    StorageLayout,
    StorageScope,
    StorageVariable,
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

    def test_layout_round_trip_preserves_scope_identity(self):
        root = 2**255
        layout = StorageLayout(
            contract_name="Namespaced",
            variables=[
                StorageVariable(
                    "owner",
                    root,
                    0,
                    32,
                    "t_uint256",
                    "uint256",
                    scope_id="erc7201:example",
                )
            ],
            types={},
            language="Solidity",
            scopes=[
                StorageScope("default", "default", 0),
                StorageScope(
                    "erc7201:example",
                    "erc7201",
                    root,
                    "erc7201:example",
                ),
            ],
        )

        self.assertEqual(StorageLayout.from_dict(layout.to_dict()), layout)

if __name__ == "__main__":
    unittest.main()
