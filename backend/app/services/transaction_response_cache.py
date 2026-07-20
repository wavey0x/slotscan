"""Bounded process-local cache for complete transaction API responses."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import AsyncIterator, Callable

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


@dataclass(frozen=True)
class _ResponseEntry:
    body: bytes
    expires_at: float | None


class TransactionResponseCache:
    """Byte-aware LRU with per-response singleflight."""

    def __init__(
        self,
        max_bytes: int,
        *,
        terminal_response_ttl_seconds: float = 60,
        clock: Callable[[], float] = monotonic,
    ):
        self.max_bytes = max(0, max_bytes)
        self.terminal_response_ttl_seconds = max(
            0.0,
            terminal_response_ttl_seconds,
        )
        self._clock = clock
        self._entries: OrderedDict[
            TransactionResponseKey,
            _ResponseEntry,
        ] = OrderedDict()
        self._size_bytes = 0
        self._locks: dict[TransactionResponseKey, _ResponseLockEntry] = {}
        self.hits = 0
        self.misses = 0
        self.stores = 0
        self.evictions = 0
        self.rejections = 0
        self.coalesced_hits = 0
        self.expirations = 0

    @property
    def size_bytes(self) -> int:
        return self._size_bytes

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def get(self, key: TransactionResponseKey) -> bytes | None:
        entry = self._get_live_entry(key)
        if entry is None:
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return entry.body

    def peek(self, key: TransactionResponseKey) -> bytes | None:
        entry = self._get_live_entry(key)
        if entry is not None:
            self._entries.move_to_end(key)
            return entry.body
        return None

    def put(
        self,
        key: TransactionResponseKey,
        body: bytes,
        *,
        ttl_seconds: float | None = None,
    ) -> bool:
        size = len(body)
        if (
            self.max_bytes == 0
            or size > self.max_bytes
            or (ttl_seconds is not None and ttl_seconds <= 0)
        ):
            self.rejections += 1
            return False

        now = self._clock()
        self._remove_expired(now)
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._size_bytes -= len(previous.body)

        while self._entries and self._size_bytes + size > self.max_bytes:
            _evicted_key, evicted = self._entries.popitem(last=False)
            self._size_bytes -= len(evicted.body)
            self.evictions += 1

        self._entries[key] = _ResponseEntry(
            body=body,
            expires_at=(
                None if ttl_seconds is None else now + ttl_seconds
            ),
        )
        self._size_bytes += size
        self.stores += 1
        return True

    def _get_live_entry(
        self,
        key: TransactionResponseKey,
    ) -> _ResponseEntry | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at is None or entry.expires_at > self._clock():
            return entry
        self._expire(key)
        return None

    def _remove_expired(self, now: float) -> None:
        expired_keys = [
            key
            for key, entry in self._entries.items()
            if entry.expires_at is not None and entry.expires_at <= now
        ]
        for key in expired_keys:
            self._expire(key)

    def _expire(self, key: TransactionResponseKey) -> None:
        entry = self._entries.pop(key)
        self._size_bytes -= len(entry.body)
        self.expirations += 1

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
