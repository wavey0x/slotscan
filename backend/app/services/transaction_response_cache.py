"""Bounded process-local cache for complete transaction API responses."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from app.services.transaction_receipt import ReceiptIdentity


@dataclass(frozen=True)
class TransactionResponseKey:
    chain_id: int
    tx_hash: str
    receipt: ReceiptIdentity
    include_global_order: bool


@dataclass
class _ResponseLockEntry:
    lock: asyncio.Lock
    users: int = 0


class TransactionResponseCache:
    """Byte-aware LRU with per-response singleflight."""

    def __init__(self, max_bytes: int):
        self.max_bytes = max(0, max_bytes)
        self._entries: OrderedDict[TransactionResponseKey, bytes] = OrderedDict()
        self._size_bytes = 0
        self._locks: dict[TransactionResponseKey, _ResponseLockEntry] = {}
        self.hits = 0
        self.misses = 0
        self.stores = 0
        self.evictions = 0
        self.rejections = 0
        self.coalesced_hits = 0

    @property
    def size_bytes(self) -> int:
        return self._size_bytes

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def get(self, key: TransactionResponseKey) -> bytes | None:
        body = self._entries.get(key)
        if body is None:
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return body

    def peek(self, key: TransactionResponseKey) -> bytes | None:
        body = self._entries.get(key)
        if body is not None:
            self._entries.move_to_end(key)
        return body

    def put(self, key: TransactionResponseKey, body: bytes) -> bool:
        size = len(body)
        if self.max_bytes == 0 or size > self.max_bytes:
            self.rejections += 1
            return False

        previous = self._entries.pop(key, None)
        if previous is not None:
            self._size_bytes -= len(previous)

        while self._entries and self._size_bytes + size > self.max_bytes:
            _evicted_key, evicted_body = self._entries.popitem(last=False)
            self._size_bytes -= len(evicted_body)
            self.evictions += 1

        self._entries[key] = body
        self._size_bytes += size
        self.stores += 1
        return True

    @asynccontextmanager
    async def hold(
        self,
        key: TransactionResponseKey,
    ) -> AsyncIterator[None]:
        entry = self._locks.get(key)
        if entry is None:
            entry = _ResponseLockEntry(asyncio.Lock())
            self._locks[key] = entry
        entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.users -= 1
            if entry.users == 0 and self._locks.get(key) is entry:
                self._locks.pop(key, None)
