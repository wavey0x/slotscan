import asyncio
import json
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.config import Settings
from app.models.domain import VerificationResult
from app.models.errors import VerificationProviderError
from app.services.verification import VerificationService


ADDRESS = "0x" + "11" * 20
HASH_A = "0x" + "aa" * 32
HASH_B = "0x" + "bb" * 32


class _StreamResponse:
    def __init__(self, body: bytes, *, status_code=200, headers=None):
        self.body = body
        self.status_code = status_code
        self.headers = headers or {}

    async def aiter_bytes(self):
        yield self.body


class _StreamContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def _stream_client(response):
    return SimpleNamespace(
        stream=Mock(return_value=_StreamContext(response)),
    )


def _verified(name="Verified"):
    return VerificationResult(
        source="sourcify",
        match_type="full",
        name=name,
        compilation_target={"src/C.sol": name},
        compiler_version="0.8.30",
        compiler_settings={"optimizer": {"enabled": True, "runs": 200}},
        sources={"src/C.sol": f"contract {name} {{}}"},
        storage_layout={"storage": [], "types": {}},
        language="Solidity",
    )


class _MemorySourceCache:
    def __init__(self):
        self.rows = {}
        self.verified_writes = []
        self.not_found_writes = []

    @staticmethod
    def _key(chain_id, code_address, code_hash):
        return chain_id, code_address.lower(), code_hash.lower()

    async def get(self, chain_id, code_address, code_hash):
        return self.rows.get(self._key(chain_id, code_address, code_hash))

    async def save_verified(
        self,
        chain_id,
        code_address,
        code_hash,
        result,
    ):
        key = self._key(chain_id, code_address, code_hash)
        self.verified_writes.append(key)
        self.rows[key] = SimpleNamespace(
            status="verified",
            result=result.to_dict(),
            checked_at=datetime.utcnow(),
        )

    async def save_not_found(self, chain_id, code_address, code_hash):
        key = self._key(chain_id, code_address, code_hash)
        self.not_found_writes.append(key)
        self.rows[key] = SimpleNamespace(
            status="not_found",
            result=None,
            checked_at=datetime.utcnow(),
        )


def _service(**settings):
    return VerificationService(
        Settings(**settings),
        http_client=object(),
    )


class VerificationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_result_survives_beyond_negative_ttl(self):
        repo = _MemorySourceCache()
        repo.rows[(1, ADDRESS, HASH_A)] = SimpleNamespace(
            status="verified",
            result=_verified().to_dict(),
            checked_at=datetime.utcnow() - timedelta(days=365),
        )
        service = _service(NO_SOURCE_CACHE_TTL_SECONDS=1)
        service._fetch_verification = AsyncMock(
            side_effect=AssertionError("verified entries do not expire")
        )

        result = await service.resolve(1, ADDRESS, HASH_A, repo)

        self.assertEqual(result, _verified())
        service._fetch_verification.assert_not_awaited()

    async def test_fresh_negative_suppresses_provider_calls(self):
        repo = _MemorySourceCache()
        repo.rows[(1, ADDRESS, HASH_A)] = SimpleNamespace(
            status="not_found",
            result=None,
            checked_at=datetime.utcnow(),
        )
        service = _service()
        service._fetch_verification = AsyncMock(
            side_effect=AssertionError("fresh misses are cached")
        )

        self.assertIsNone(await service.resolve(1, ADDRESS, HASH_A, repo))
        service._fetch_verification.assert_not_awaited()

    async def test_expired_negative_performs_one_new_lookup(self):
        repo = _MemorySourceCache()
        repo.rows[(1, ADDRESS, HASH_A)] = SimpleNamespace(
            status="not_found",
            result=None,
            checked_at=datetime.utcnow() - timedelta(seconds=901),
        )
        service = _service(NO_SOURCE_CACHE_TTL_SECONDS=900)
        service._fetch_verification = AsyncMock(return_value=None)

        self.assertIsNone(await service.resolve(1, ADDRESS, HASH_A, repo))

        service._fetch_verification.assert_awaited_once_with(1, ADDRESS)
        self.assertEqual(repo.not_found_writes, [(1, ADDRESS, HASH_A)])

    async def test_concurrent_cold_requests_share_one_lookup(self):
        repo = _MemorySourceCache()
        service = _service()
        started = asyncio.Event()
        release = asyncio.Event()

        async def fetch(chain_id, address):
            started.set()
            await release.wait()
            return _verified()

        service._fetch_verification = AsyncMock(side_effect=fetch)
        tasks = [
            asyncio.create_task(service.resolve(1, ADDRESS, HASH_A, repo))
            for _ in range(8)
        ]
        await started.wait()
        release.set()

        results = await asyncio.gather(*tasks)

        self.assertTrue(all(result == _verified() for result in results))
        service._fetch_verification.assert_awaited_once_with(1, ADDRESS)
        self.assertEqual(repo.verified_writes, [(1, ADDRESS, HASH_A)])
        self.assertEqual(service._in_flight, {})

    async def test_cancelled_leader_removes_in_flight_entry(self):
        repo = _MemorySourceCache()
        service = _service()
        started = asyncio.Event()

        async def fetch(chain_id, address):
            started.set()
            await asyncio.Event().wait()

        service._fetch_verification = AsyncMock(side_effect=fetch)
        leader = asyncio.create_task(
            service.resolve(1, ADDRESS, HASH_A, repo)
        )
        await started.wait()
        leader.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await leader

        self.assertEqual(service._in_flight, {})
        self.assertEqual(repo.not_found_writes, [])
        self.assertEqual(repo.verified_writes, [])

    async def test_code_hash_change_causes_a_miss(self):
        repo = _MemorySourceCache()
        repo.rows[(1, ADDRESS, HASH_A)] = SimpleNamespace(
            status="verified",
            result=_verified("Old").to_dict(),
            checked_at=datetime.utcnow(),
        )
        service = _service()
        service._fetch_verification = AsyncMock(return_value=_verified("New"))

        old = await service.resolve(1, ADDRESS, HASH_A, repo)
        new = await service.resolve(1, ADDRESS, HASH_B, repo)

        self.assertEqual(old.name, "Old")
        self.assertEqual(new.name, "New")
        service._fetch_verification.assert_awaited_once_with(1, ADDRESS)
        self.assertEqual(repo.verified_writes, [(1, ADDRESS, HASH_B)])

    async def test_sourcify_success_bypasses_etherscan_and_is_cached(self):
        repo = _MemorySourceCache()
        service = _service()
        service._try_sourcify = AsyncMock(return_value=_verified())
        service._try_etherscan = AsyncMock(
            side_effect=AssertionError("Sourcify success must short-circuit")
        )

        first = await service.resolve(1, ADDRESS, HASH_A, repo)
        second = await service.resolve(1, ADDRESS, HASH_A, repo)

        self.assertEqual(first, second)
        service._try_sourcify.assert_awaited_once_with(1, ADDRESS)
        service._try_etherscan.assert_not_awaited()
        self.assertEqual(repo.verified_writes, [(1, ADDRESS, HASH_A)])

    async def test_sourcify_miss_then_etherscan_success_is_cached(self):
        repo = _MemorySourceCache()
        service = _service()
        etherscan = _verified()
        etherscan.source = "etherscan"
        service._try_sourcify = AsyncMock(return_value=None)
        service._try_etherscan = AsyncMock(return_value=etherscan)

        result = await service.resolve(1, ADDRESS, HASH_A, repo)

        self.assertEqual(result.source, "etherscan")
        service._try_sourcify.assert_awaited_once_with(1, ADDRESS)
        service._try_etherscan.assert_awaited_once_with(1, ADDRESS)
        self.assertEqual(repo.verified_writes, [(1, ADDRESS, HASH_A)])

    async def test_clean_provider_misses_create_negative_entry(self):
        repo = _MemorySourceCache()
        service = _service()
        service._try_sourcify = AsyncMock(return_value=None)
        service._try_etherscan = AsyncMock(return_value=None)

        self.assertIsNone(await service.resolve(1, ADDRESS, HASH_A, repo))

        self.assertEqual(repo.not_found_writes, [(1, ADDRESS, HASH_A)])
        self.assertEqual(repo.verified_writes, [])

    async def test_any_provider_failure_prevents_negative_caching(self):
        cases = (
            (
                VerificationProviderError(["sourcify timeout"]),
                None,
            ),
            (
                None,
                VerificationProviderError(["etherscan HTTP 500"]),
            ),
        )
        for sourcify, etherscan in cases:
            with self.subTest(sourcify=sourcify, etherscan=etherscan):
                repo = _MemorySourceCache()
                service = _service()
                service._try_sourcify = AsyncMock(
                    side_effect=sourcify
                    if isinstance(sourcify, Exception)
                    else None,
                    return_value=None,
                )
                service._try_etherscan = AsyncMock(
                    side_effect=etherscan
                    if isinstance(etherscan, Exception)
                    else None,
                    return_value=None,
                )

                with self.assertRaises(VerificationProviderError):
                    await service.resolve(1, ADDRESS, HASH_A, repo)

                self.assertEqual(repo.not_found_writes, [])
                self.assertEqual(repo.verified_writes, [])

    async def test_global_provider_concurrency_is_limited(self):
        repo = _MemorySourceCache()
        service = _service(MAX_PARALLEL_VERIFICATION_REQUESTS=2)
        active = 0
        peak = 0
        lock = asyncio.Lock()

        async def fetch(chain_id, address):
            nonlocal active, peak
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.01)
            async with lock:
                active -= 1
            return _verified(address[-4:])

        service._fetch_verification = AsyncMock(side_effect=fetch)
        await asyncio.gather(*(
            service.resolve(
                1,
                f"0x{index:040x}",
                f"0x{index:064x}",
                repo,
            )
            for index in range(8)
        ))

        self.assertEqual(peak, 2)

    async def test_sourcify_v2_payload_is_normalized(self):
        body = json.dumps(
            {
                "match": "match",
                "storageLayout": {
                    "storage": [{"label": "owner"}],
                    "types": {},
                },
                "compilation": {
                    "language": "Solidity",
                    "compilerVersion": "0.8.26+commit.8a97fa7a",
                    "compilerSettings": {"optimizer": {"enabled": True}},
                    "name": "C",
                    "fullyQualifiedName": "src/C.sol:C",
                },
                "sources": {"src/C.sol": {"content": "contract C {}"}},
            }
        ).encode()
        client = _stream_client(_StreamResponse(body))
        service = VerificationService(Settings(), client)

        result = await service._try_sourcify(1, ADDRESS)

        self.assertEqual(result.name, "C")
        self.assertEqual(result.compilation_target, {"src/C.sol": "C"})
        self.assertEqual(result.storage_layout["storage"][0]["label"], "owner")
        self.assertEqual(result.sources, {"src/C.sol": "contract C {}"})

    async def test_etherscan_similar_match_is_not_exact_verification(self):
        body = json.dumps(
            {
                "status": "1",
                "message": "OK",
                "result": [
                    {
                        "SourceCode": "contract C {}",
                        "ContractName": "C",
                        "CompilerVersion": "v0.8.30+commit.73712a01",
                        "OptimizationUsed": "0",
                        "Runs": "200",
                        "EVMVersion": "default",
                        "SimilarMatch": "0x" + "22" * 20,
                    }
                ],
            }
        ).encode()
        service = VerificationService(
            Settings(ETHERSCAN_API_KEY_1="key"),
            _stream_client(_StreamResponse(body)),
        )

        self.assertIsNone(await service._try_etherscan(1, ADDRESS))

    async def test_verification_response_limit_counts_decoded_bytes(self):
        body = json.dumps(
            {
                "match": "match",
                "compilation": {},
                "sources": {},
            }
        ).encode()
        response = _StreamResponse(
            body,
            headers={"content-length": "1"},
        )
        admitted = VerificationService(
            Settings(MAX_VERIFICATION_RESPONSE_BYTES=len(body)),
            _stream_client(response),
        )
        rejected = VerificationService(
            Settings(MAX_VERIFICATION_RESPONSE_BYTES=len(body) - 1),
            _stream_client(response),
        )

        self.assertIsNotNone(await admitted._try_sourcify(1, ADDRESS))
        with self.assertRaisesRegex(
            VerificationProviderError,
            "response too large",
        ):
            await rejected._try_sourcify(1, ADDRESS)


if __name__ == "__main__":
    unittest.main()
