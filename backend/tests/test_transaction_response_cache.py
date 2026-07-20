import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Response

from app.api.routes.transactions import (
    _response_cache_policy,
    get_transaction_storage_history,
)
from app.models.api import (
    ContractHistoryCountsResponse,
    ContractHistoryResponse,
    ContractResolutionResponse,
    TransactionCapabilitiesResponse,
    TransactionStorageHistoryResponse,
    TransactionSummaryResponse,
)
from app.services.transaction_receipt import ReceiptIdentity
from app.services.transaction_response_cache import (
    TransactionResponseCache,
    TransactionResponseKey,
)


TX_HASH = "0x" + "ab" * 32
BLOCK_HASH = "0x" + "cd" * 32


def receipt(block_hash=BLOCK_HASH):
    return {
        "blockHash": block_hash,
        "blockNumber": 123,
        "transactionIndex": 4,
        "status": 1,
    }


def response(*, complete=True):
    return TransactionStorageHistoryResponse(
        chain_id=1,
        tx_hash=TX_HASH,
        block_number=123,
        status="success",
        capabilities=TransactionCapabilitiesResponse(
            write_history_complete=complete,
            values_complete=complete,
            rollback_classification_complete=complete,
            execution_order_available=complete,
            final_state_values_available=complete,
            state_reconciliation_complete=complete,
            address_attribution_complete=complete,
            code_attribution_complete=complete,
        ),
        summary=TransactionSummaryResponse(
            storage_owners=0,
            slots_written=0,
            sstore_events=0,
            net_changed_slots=0,
            restored_slots=0,
            reverted_only_slots=0,
            noop_only_slots=0,
            reverted_writes=0,
            noop_writes=0,
            resolved_slots=0,
        ),
        contracts=[],
        global_order=None,
        is_complete=complete,
        trace_unavailable=False,
        degraded_reason=None if complete else "trace_limit",
    )


def contract(**updates):
    values = {
        "storage_address": "0x" + "12" * 20,
        "is_verified": True,
        "layout_available": True,
        "resolution_status": "resolved",
        "resolution": ContractResolutionResponse(resolved=1, total=1),
        "counts": ContractHistoryCountsResponse(
            slots_written=1,
            sstore_events=1,
            net_changed_slots=1,
            restored_slots=0,
            reverted_only_slots=0,
            noop_only_slots=0,
            reverted_writes=0,
            noop_writes=0,
        ),
    }
    values.update(updates)
    return ContractHistoryResponse(**values)


def no_source_contract(**updates):
    return contract(
        is_verified=False,
        layout_available=False,
        resolution_status="no_verified_source",
        **updates,
    )


def history_service(receipts):
    return SimpleNamespace(
        tracer=SimpleNamespace(
            rpc_client=SimpleNamespace(
                get_receipt=AsyncMock(side_effect=receipts),
            )
        )
    )


def key(
    *,
    block_hash=BLOCK_HASH,
    include_global_order=False,
):
    return TransactionResponseKey(
        chain_id=1,
        tx_hash=TX_HASH,
        receipt=ReceiptIdentity.from_receipt(receipt(block_hash)),
        include_global_order=include_global_order,
    )


class TransactionResponseCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_requests_build_once_and_return_identical_bytes(self):
        cache = TransactionResponseCache(1024 * 1024)
        service = history_service([receipt()] * 8)
        expected = response()

        async def build(**_kwargs):
            await asyncio.sleep(0.01)
            return expected

        with patch(
            "app.api.routes.transactions._build_transaction_storage_history",
            AsyncMock(side_effect=build),
        ) as builder:
            results = await asyncio.gather(*(
                get_transaction_storage_history(
                    chain_id=1,
                    tx_hash=TX_HASH,
                    include_global_order=False,
                    history_service=service,
                    response_cache=cache,
                )
                for _ in range(8)
            ))

        expected_body = expected.model_dump_json().encode()
        self.assertEqual(builder.await_count, 1)
        self.assertTrue(all(isinstance(result, Response) for result in results))
        self.assertTrue(all(result.body == expected_body for result in results))
        self.assertEqual(cache.entry_count, 1)
        self.assertEqual(cache.coalesced_hits, 7)
        self.assertEqual(cache._locks, {})

    async def test_receipt_and_response_shape_are_part_of_cache_identity(self):
        changed_hash = "0x" + "ef" * 32
        cache = TransactionResponseCache(1024 * 1024)
        service = history_service([
            receipt(),
            receipt(),
            receipt(),
            receipt(changed_hash),
        ])
        expected = response()

        with patch(
            "app.api.routes.transactions._build_transaction_storage_history",
            AsyncMock(return_value=expected),
        ) as builder:
            first = await get_transaction_storage_history(
                1,
                TX_HASH,
                False,
                service,
                cache,
            )
            repeated = await get_transaction_storage_history(
                1,
                TX_HASH,
                False,
                service,
                cache,
            )
            timeline = await get_transaction_storage_history(
                1,
                TX_HASH,
                True,
                service,
                cache,
            )
            reorged = await get_transaction_storage_history(
                1,
                TX_HASH,
                False,
                service,
                cache,
            )

        self.assertEqual(builder.await_count, 3)
        self.assertEqual(first.body, repeated.body)
        self.assertEqual(first.body, timeline.body)
        self.assertEqual(first.body, reorged.body)
        self.assertEqual(cache.entry_count, 3)

    async def test_incomplete_response_is_never_cached(self):
        cache = TransactionResponseCache(1024 * 1024)
        service = history_service([receipt(), receipt()])
        incomplete = response(complete=False)

        with patch(
            "app.api.routes.transactions._build_transaction_storage_history",
            AsyncMock(return_value=incomplete),
        ) as builder:
            first = await get_transaction_storage_history(
                1,
                TX_HASH,
                False,
                service,
                cache,
            )
            second = await get_transaction_storage_history(
                1,
                TX_HASH,
                False,
                service,
                cache,
            )

        self.assertIs(first, incomplete)
        self.assertIs(second, incomplete)
        self.assertEqual(builder.await_count, 2)
        self.assertEqual(cache.entry_count, 0)

    def test_only_final_resolved_responses_are_cacheable(self):
        complete = response().model_copy(update={"contracts": [contract()]})
        self.assertEqual(
            _response_cache_policy(complete, 60),
            (True, None),
        )

        for unsafe_contract in (
            contract(is_verified=False),
            contract(layout_available=False),
            contract(resolution_status="timed_out"),
            contract(errors=["layout failed"]),
        ):
            candidate = complete.model_copy(
                update={"contracts": [unsafe_contract]},
            )
            self.assertEqual(
                _response_cache_policy(candidate, 60),
                (False, None),
            )

    def test_terminal_no_source_response_has_short_cache_lifetime(self):
        candidate = response().model_copy(
            update={"contracts": [contract(), no_source_contract()]},
        )

        self.assertEqual(
            _response_cache_policy(candidate, 60),
            (True, 60),
        )
        self.assertEqual(
            _response_cache_policy(candidate, 0),
            (False, None),
        )

    def test_retryable_or_degraded_responses_are_not_cached(self):
        complete = response()
        candidates = (
            complete.model_copy(
                update={
                    "contracts": [
                        no_source_contract(errors=["source request failed"]),
                    ],
                },
            ),
            complete.model_copy(
                update={
                    "contracts": [contract(resolution_status="timed_out")],
                },
            ),
            complete.model_copy(
                update={
                    "contracts": [contract(resolution_status="failed")],
                },
            ),
            complete.model_copy(
                update={
                    "contracts": [contract(resolution_status="not_resolved")],
                },
            ),
            response(complete=False).model_copy(
                update={"contracts": [no_source_contract()]},
            ),
            complete.model_copy(
                update={
                    "contracts": [no_source_contract()],
                    "trace_unavailable": True,
                },
            ),
        )

        for candidate in candidates:
            with self.subTest(candidate=candidate):
                self.assertEqual(
                    _response_cache_policy(candidate, 60),
                    (False, None),
                )

    async def test_terminal_response_expires_and_is_rebuilt(self):
        now = 1000.0
        cache = TransactionResponseCache(
            1024 * 1024,
            terminal_response_ttl_seconds=60,
            clock=lambda: now,
        )
        service = history_service([receipt()] * 3)
        terminal = response().model_copy(
            update={"contracts": [no_source_contract()]},
        )

        with patch(
            "app.api.routes.transactions._build_transaction_storage_history",
            AsyncMock(return_value=terminal),
        ) as builder:
            first = await get_transaction_storage_history(
                1,
                TX_HASH,
                False,
                service,
                cache,
            )
            now += 59
            cached = await get_transaction_storage_history(
                1,
                TX_HASH,
                False,
                service,
                cache,
            )
            now += 1
            rebuilt = await get_transaction_storage_history(
                1,
                TX_HASH,
                False,
                service,
                cache,
            )

        expected_body = terminal.model_dump_json().encode()
        self.assertEqual(builder.await_count, 2)
        self.assertEqual(first.body, expected_body)
        self.assertEqual(cached.body, expected_body)
        self.assertEqual(rebuilt.body, expected_body)
        self.assertEqual(cache.entry_count, 1)
        self.assertEqual(cache.expirations, 1)

    def test_fully_resolved_response_does_not_expire(self):
        now = 1000.0
        cache = TransactionResponseCache(1024, clock=lambda: now)
        cache_key = key()

        self.assertTrue(cache.put(cache_key, b"complete"))
        now += 24 * 60 * 60

        self.assertEqual(cache.get(cache_key), b"complete")
        self.assertEqual(cache.expirations, 0)

    def test_expiry_reclaims_bytes_without_evicting_live_entries(self):
        now = 1000.0
        cache = TransactionResponseCache(6, clock=lambda: now)
        expiring = key()
        live = key(include_global_order=True)
        added = key(block_hash="0x" + "ef" * 32)

        self.assertTrue(cache.put(expiring, b"aaa", ttl_seconds=1))
        self.assertTrue(cache.put(live, b"bb"))
        now += 1
        self.assertTrue(cache.put(added, b"cccc"))

        self.assertIsNone(cache.peek(expiring))
        self.assertEqual(cache.peek(live), b"bb")
        self.assertEqual(cache.peek(added), b"cccc")
        self.assertEqual(cache.size_bytes, 6)
        self.assertEqual(cache.expirations, 1)
        self.assertEqual(cache.evictions, 0)

    async def test_byte_bound_is_lru_and_rejects_oversized_entries(self):
        cache = TransactionResponseCache(6)
        first = key()
        second = key(include_global_order=True)
        third = key(block_hash="0x" + "ef" * 32)

        self.assertTrue(cache.put(first, b"aaa"))
        self.assertTrue(cache.put(second, b"bb"))
        self.assertEqual(cache.get(first), b"aaa")
        self.assertTrue(cache.put(third, b"ccc"))

        self.assertIsNone(cache.peek(second))
        self.assertEqual(cache.peek(first), b"aaa")
        self.assertEqual(cache.peek(third), b"ccc")
        self.assertEqual(cache.size_bytes, 6)
        self.assertEqual(cache.evictions, 1)
        self.assertFalse(cache.put(second, b"1234567"))
        self.assertFalse(cache.put(second, b"ok", ttl_seconds=0))
        self.assertEqual(cache.rejections, 2)

    async def test_cancelled_waiter_does_not_leak_singleflight_entry(self):
        cache = TransactionResponseCache(1024)
        entered = asyncio.Event()
        release = asyncio.Event()
        cache_key = key()

        async def hold():
            async with cache.hold(cache_key):
                entered.set()
                await release.wait()

        leader = asyncio.create_task(hold())
        await entered.wait()
        waiter = asyncio.create_task(hold())
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        release.set()
        await leader

        self.assertEqual(cache._locks, {})
