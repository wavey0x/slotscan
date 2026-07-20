"""Exact mined-transaction receipt identity."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.errors import RPCError


@dataclass(frozen=True)
class ReceiptIdentity:
    """Canonical identity required to reuse transaction-derived evidence."""

    block_hash: str
    block_number: int
    transaction_index: int
    root_succeeded: bool

    @classmethod
    def from_receipt(cls, receipt: dict) -> "ReceiptIdentity":
        try:
            status = cls._quantity(receipt["status"])
            if status not in {0, 1}:
                raise ValueError("receipt status must be zero or one")
            return cls(
                block_hash=cls._hash(receipt["blockHash"]),
                block_number=cls._quantity(receipt["blockNumber"]),
                transaction_index=cls._quantity(receipt["transactionIndex"]),
                root_succeeded=status == 1,
            )
        except (KeyError, TypeError, ValueError):
            raise RPCError(
                "eth_getTransactionReceipt",
                "receipt identity is malformed",
            ) from None

    @staticmethod
    def _hash(value) -> str:
        if isinstance(value, bytes):
            value = "0x" + value.hex()
        elif not isinstance(value, str) and hasattr(value, "hex"):
            value = value.hex()
        if (
            not isinstance(value, str)
            or len(value) != 66
            or not value.startswith("0x")
        ):
            raise ValueError("invalid hash")
        bytes.fromhex(value[2:])
        return value.lower()

    @staticmethod
    def _quantity(value) -> int:
        if isinstance(value, bool):
            raise ValueError("invalid quantity")
        if isinstance(value, int):
            result = value
        elif isinstance(value, str):
            result = int(value, 16)
        else:
            raise TypeError("invalid quantity")
        if result < 0:
            raise ValueError("negative quantity")
        return result
