import unittest
from unittest.mock import AsyncMock

from web3 import Web3

from app.config import Settings
from app.models.domain import (
    StorageLayout,
    StorageType,
    StorageVariable,
    VerificationResult,
)
from app.services.resolver import ContractResolver, _parse_eip7702_designator


AUTHORITY = Web3.to_checksum_address("0x" + "11" * 20)
DELEGATE = Web3.to_checksum_address("0x" + "22" * 20)
SECOND_DELEGATE = Web3.to_checksum_address("0x" + "33" * 20)
DESIGNATOR = bytes.fromhex("ef0100") + bytes.fromhex(DELEGATE[2:])
DELEGATE_DESIGNATOR = (
    bytes.fromhex("ef0100") + bytes.fromhex(SECOND_DELEGATE[2:])
)


def _layout() -> StorageLayout:
    value_type = StorageType(
        id="t_address",
        label="address",
        kind="value",
        encoding="inplace",
        num_bytes=20,
    )
    return StorageLayout(
        contract_name="DelegateWallet",
        variables=[
            StorageVariable(
                name="owner",
                slot=0,
                offset=0,
                size=20,
                type_id=value_type.id,
                label=value_type.label,
            )
        ],
        types={value_type.id: value_type},
    )


class _CodeProvider:
    def __init__(self, codes):
        self.codes = {address.lower(): code for address, code in codes.items()}
        self.code_calls = []

    async def get_code(self, chain_id, address, block):
        self.code_calls.append((chain_id, address, block))
        return self.codes.get(address.lower(), b"")


class _NoWriteRepository:
    def __init__(self):
        self.save_calls = []

    async def get_at_block(self, chain_id, address, block_number):
        return None

    async def get_layout_by_code_hash(self, code_hash):
        return None

    async def save(self, metadata):
        self.save_calls.append(("latest", metadata.address))

    async def save_at_block(self, metadata, block_number):
        self.save_calls.append((block_number, metadata.address))


class DesignatorTests(unittest.TestCase):
    def test_exact_designator_is_parsed(self):
        self.assertEqual(_parse_eip7702_designator(DESIGNATOR), DELEGATE)

    def test_wrong_prefix_or_length_is_not_parsed(self):
        cases = (
            bytes.fromhex("ef0101") + bytes.fromhex(DELEGATE[2:]),
            DESIGNATOR[:-1],
            DESIGNATOR + b"\x00",
            b"\xef\x01\x00",
        )
        for bytecode in cases:
            with self.subTest(bytecode=bytecode.hex()):
                self.assertIsNone(_parse_eip7702_designator(bytecode))


class DelegatedResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_delegate_layout_is_composed_with_authority_identity(self):
        provider = _CodeProvider(
            {
                AUTHORITY: DESIGNATOR,
                DELEGATE: b"\x60\x00",
            }
        )
        repository = _NoWriteRepository()
        source_cache = object()
        verification_service = AsyncMock()
        verification_service.resolve.return_value = VerificationResult(
            source="sourcify",
            match_type="full",
            name="DelegateWallet",
            compiler_version="0.8.30",
            storage_layout=_layout().to_dict(),
        )
        resolver = ContractResolver(
            provider,
            Settings(),
            verification_service=verification_service,
            source_cache_repo=source_cache,
            contract_repo=repository,
        )
        resolver.detect_proxy = AsyncMock(
            side_effect=AssertionError(
                "proxy detection must not run for the authority or direct delegate"
            )
        )

        result = await resolver.resolve(1, AUTHORITY, block_number=123)

        self.assertEqual(result.address, AUTHORITY)
        self.assertTrue(result.is_delegated)
        self.assertEqual(result.delegate_address, DELEGATE)
        self.assertEqual(result.code_hash, Web3.keccak(DESIGNATOR).hex())
        self.assertEqual(
            result.delegate_code_hash,
            Web3.keccak(b"\x60\x00").hex(),
        )
        self.assertFalse(result.is_proxy)
        self.assertTrue(result.is_verified)
        self.assertEqual(result.storage_layout.contract_name, "DelegateWallet")
        verification_service.resolve.assert_awaited_once_with(
            1,
            DELEGATE,
            Web3.keccak(b"\x60\x00").hex(),
            source_cache,
        )
        self.assertEqual(repository.save_calls, [])

    async def test_empty_delegate_returns_delegated_metadata_without_layout(self):
        verification_service = AsyncMock()
        verification_service.resolve.side_effect = AssertionError(
            "empty delegates cannot be verified"
        )
        resolver = ContractResolver(
            _CodeProvider({AUTHORITY: DESIGNATOR}),
            Settings(),
            verification_service=verification_service,
            source_cache_repo=object(),
        )

        result = await resolver.resolve(1, AUTHORITY, block_number=123)

        self.assertTrue(result.is_delegated)
        self.assertEqual(result.delegate_address, DELEGATE)
        self.assertIsNone(result.delegate_code_hash)
        self.assertIsNone(result.storage_layout)
        verification_service.resolve.assert_not_awaited()

    async def test_delegate_to_delegate_stops_after_one_hop(self):
        provider = _CodeProvider(
            {
                AUTHORITY: DESIGNATOR,
                DELEGATE: DELEGATE_DESIGNATOR,
                SECOND_DELEGATE: b"\x60\x00",
            }
        )
        verification_service = AsyncMock()
        verification_service.resolve.side_effect = AssertionError(
            "a second delegation must not be followed"
        )
        resolver = ContractResolver(
            provider,
            Settings(),
            verification_service=verification_service,
            source_cache_repo=object(),
        )

        result = await resolver.resolve(1, AUTHORITY, block_number=123)

        self.assertEqual(result.delegate_address, DELEGATE)
        self.assertEqual(
            result.delegate_code_hash,
            Web3.keccak(DELEGATE_DESIGNATOR).hex(),
        )
        self.assertIsNone(result.storage_layout)
        self.assertNotIn(
            SECOND_DELEGATE.lower(),
            [call[1].lower() for call in provider.code_calls],
        )
        verification_service.resolve.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
