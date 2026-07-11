import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.config import Settings
from app.models.domain import VerificationResult
from app.services.namespace_storage import NamespaceStorageParser
from app.services.resolver import ContractResolver


ADDRESS = "0x" + "11" * 20


class NamespaceParserTests(unittest.TestCase):
    def test_inferred_layout_sizes_interface_uint96_and_static_array(self):
        parser = NamespaceStorageParser()
        members = parser.parse_struct_members(
            "IERC20 token; uint96 amount; uint256[2] values;"
        )
        self.assertEqual(
            [(m.name, m.slot_offset, m.byte_offset, m.size) for m in members],
            [
                ("token", 0, 0, 20),
                ("amount", 0, 20, 12),
                ("values", 1, 0, 64),
            ],
        )

    def test_all_detected_namespaces_are_returned_as_inferred(self):
        sources = {
            "A.sol": """
                struct A { uint96 amount; }
                library LA {
                    bytes32 private constant SLOT_A = 0x100;
                    function load() internal pure returns (A storage $) {
                        assembly { $.slot := SLOT_A }
                    }
                }
            """,
            "B.sol": """
                struct B { address owner; }
                library LB {
                    bytes32 private constant SLOT_B = 0x200;
                    function load() internal pure returns (B storage $) {
                        assembly { $.slot := SLOT_B }
                    }
                }
            """,
        }
        layout = NamespaceStorageParser().parse_namespaced_storage(sources)
        self.assertEqual({v.name for v in layout.variables}, {"amount", "owner"})
        self.assertTrue(all(v.provenance == "source_inference" for v in layout.variables))
        self.assertTrue(all(v.confidence == "inferred" for v in layout.variables))


class _Resolver(ContractResolver):
    async def _check_is_contract(self, chain_id, address, block):
        return b"\x60\x00"

    async def detect_proxy(self, chain_id, address, block=None, bytecode=None):
        return None

    async def _fetch_verification(self, chain_id, address):
        return VerificationResult(
            source="sourcify",
            match_type="full",
            name="AlreadyLaidOut",
            compiler_version="0.8.30",
            sources={"C.sol": "contract AlreadyLaidOut {}"},
            storage_layout={"storage": [], "types": {}},
            language="Solidity",
        )


class ResolverRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_sourcify_v2_layout_is_parsed_without_sources_or_compilation(self):
        response = SimpleNamespace(
            status_code=200,
            json=lambda: {
                "match": "match",
                "storageLayout": {
                    "storage": [
                        {
                            "astId": 1,
                            "contract": "C.sol:C",
                            "label": "owner",
                            "offset": 0,
                            "slot": "0",
                            "type": "t_address",
                        }
                    ],
                    "types": {
                        "t_address": {
                            "encoding": "inplace",
                            "label": "address",
                            "numberOfBytes": "20",
                        }
                    },
                },
                "compilation": {
                    "language": "Solidity",
                    "compilerVersion": "0.8.26+commit.8a97fa7a",
                    "compilerSettings": {"optimizer": {"enabled": True}},
                    "name": "C",
                    "fullyQualifiedName": "src/C.sol:C",
                },
            },
        )
        client = SimpleNamespace(get=AsyncMock(return_value=response))
        resolver = ContractResolver(object(), Settings(), http_client=client)

        result = await resolver._try_sourcify(1, ADDRESS)

        self.assertEqual(result.name, "C")
        self.assertEqual(result.compilation_target, {"src/C.sol": "C"})
        self.assertEqual(result.storage_layout["storage"][0]["label"], "owner")
        self.assertIsNone(result.sources)
        client.get.assert_awaited_once_with(
            f"https://sourcify.dev/server/v2/contract/1/{ADDRESS}",
            params={"fields": "storageLayout,compilation"},
        )

    async def test_verified_sources_without_layout_are_not_compiled_by_resolver(self):
        class SourceOnlyResolver(_Resolver):
            async def _fetch_verification(self, chain_id, address):
                return VerificationResult(
                    source="etherscan",
                    match_type="full",
                    name="NeedsCompilation",
                    compiler_version="0.8.30",
                    sources={"C.sol": "contract NeedsCompilation {}"},
                    storage_layout=None,
                )

        parser = SimpleNamespace(
            parse_from_raw_layout=AsyncMock(side_effect=AssertionError("not expected")),
            parse_with_artifact=AsyncMock(side_effect=AssertionError("must not compile")),
            parse_vyper_with_artifact=AsyncMock(
                side_effect=AssertionError("must not compile")
            ),
        )
        resolver = SourceOnlyResolver(object(), Settings(), layout_parser=parser)

        metadata = await resolver.resolve(1, ADDRESS)

        self.assertTrue(metadata.is_verified)
        self.assertIsNone(metadata.storage_layout)
        parser.parse_with_artifact.assert_not_awaited()
        parser.parse_vyper_with_artifact.assert_not_awaited()

    async def test_sourcify_only_mode_does_not_fall_back_to_source_apis(self):
        class SourcifyOnlyResolver(_Resolver):
            async def _try_sourcify(self, chain_id, address):
                return None

            async def _fetch_verification(self, chain_id, address):
                raise AssertionError("source fallback must not run")

        resolver = SourcifyOnlyResolver(object(), Settings())

        metadata = await resolver.resolve(
            1,
            ADDRESS,
            sourcify_layout_only=True,
        )

        self.assertFalse(metadata.is_verified)
        self.assertIsNone(metadata.storage_layout)

    async def test_supplied_storage_layout_does_not_leave_language_unbound(self):
        resolver = _Resolver(object(), Settings())
        resolver.namespace_parser.parse_namespaced_storage = lambda sources: None
        metadata = await resolver.resolve(1, ADDRESS)
        self.assertEqual(metadata.storage_layout.contract_name, "AlreadyLaidOut")

    async def test_historical_resolution_uses_block_specific_cache(self):
        expected = SimpleNamespace(
            is_verified=True,
            storage_layout={"contract_name": "Cached", "variables": [], "types": {}},
        )

        class Repo:
            async def get_at_block(self, chain_id, address, block_number):
                self.lookup = (chain_id, address, block_number)
                return expected

            def to_metadata(self, row):
                from app.models.domain import ContractMetadata, StorageLayout

                return ContractMetadata(
                    chain_id=1,
                    address=ADDRESS,
                    is_verified=True,
                    storage_layout=StorageLayout.from_dict(row.storage_layout),
                    compiler_artifact_fingerprint=None,
                )

        repo = Repo()
        resolver = _Resolver(object(), Settings(), contract_repo=repo)
        metadata = await resolver.resolve(1, ADDRESS, block_number=123)
        self.assertEqual(repo.lookup[2], 123)
        self.assertEqual(metadata.storage_layout.contract_name, "Cached")


if __name__ == "__main__":
    unittest.main()
