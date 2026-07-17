"""Shared source-verification lookup, caching, and request coalescing."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

import httpx

from app.config import Settings
from app.models.domain import VerificationResult
from app.models.errors import VerificationProviderError
from app.repositories.source_cache import SourceCacheRepository


logger = logging.getLogger(__name__)

SourceIdentity = tuple[int, str, str]


class VerificationService:
    """Resolve normalized provider data once per exact runtime-code identity."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient,
    ):
        self.settings = settings
        self.http_client = http_client
        self._provider_semaphore = asyncio.Semaphore(
            max(1, settings.max_parallel_verification_requests)
        )
        self._in_flight: dict[
            SourceIdentity,
            asyncio.Future[VerificationResult | None],
        ] = {}

    async def resolve(
        self,
        chain_id: int,
        code_address: str,
        code_hash: str,
        cache_repo: SourceCacheRepository,
    ) -> VerificationResult | None:
        """Return a cached result or coalesce one provider lookup for the key."""
        key = (chain_id, code_address.lower(), code_hash.lower())
        cached, usable = await self._read_cache(key, cache_repo)
        if usable:
            return cached

        in_flight = self._in_flight.get(key)
        if in_flight is not None:
            logger.info(
                "verification single-flight join",
                extra={
                    "chain_id": chain_id,
                    "code_address": key[1],
                    "code_hash": key[2],
                },
            )
            return await asyncio.shield(in_flight)

        leader_result = asyncio.get_running_loop().create_future()
        self._in_flight[key] = leader_result
        try:
            result = await self._resolve_as_leader(key, cache_repo)
        except asyncio.CancelledError:
            leader_result.cancel()
            raise
        except BaseException as exc:
            leader_result.set_exception(exc)
            # The leader also raises directly. Mark the future's exception as
            # observed in case no follower joined it.
            leader_result.exception()
            raise
        else:
            leader_result.set_result(result)
            return result
        finally:
            if self._in_flight.get(key) is leader_result:
                self._in_flight.pop(key, None)

    async def _resolve_as_leader(
        self,
        key: SourceIdentity,
        cache_repo: SourceCacheRepository,
    ) -> VerificationResult | None:
        cached, usable = await self._read_cache(key, cache_repo)
        if usable:
            return cached

        chain_id, code_address, code_hash = key
        async with self._provider_semaphore:
            result = await self._fetch_verification(chain_id, code_address)

        if result is not None:
            await cache_repo.save_verified(
                chain_id,
                code_address,
                code_hash,
                result,
            )
            logger.info(
                "verification cache write",
                extra={
                    "cache_status": "verified",
                    "chain_id": chain_id,
                    "code_address": code_address,
                    "code_hash": code_hash,
                    "provider": result.source,
                },
            )
            return result

        await cache_repo.save_not_found(chain_id, code_address, code_hash)
        logger.info(
            "verification cache write",
            extra={
                "cache_status": "not_found",
                "chain_id": chain_id,
                "code_address": code_address,
                "code_hash": code_hash,
            },
        )
        return None

    async def _read_cache(
        self,
        key: SourceIdentity,
        cache_repo: SourceCacheRepository,
    ) -> tuple[VerificationResult | None, bool]:
        chain_id, code_address, code_hash = key
        row = await cache_repo.get(chain_id, code_address, code_hash)
        if row is None:
            return None, False
        if row.status == "verified":
            if not isinstance(row.result, dict):
                raise ValueError("verified source cache entry has no result")
            logger.info(
                "verification cache hit",
                extra={
                    "cache_status": "verified",
                    "chain_id": chain_id,
                    "code_address": code_address,
                    "code_hash": code_hash,
                },
            )
            return VerificationResult.from_dict(row.result), True
        if row.status == "not_found" and self._negative_is_fresh(row.checked_at):
            logger.info(
                "verification cache hit",
                extra={
                    "cache_status": "not_found",
                    "chain_id": chain_id,
                    "code_address": code_address,
                    "code_hash": code_hash,
                },
            )
            return None, True
        if row.status == "not_found":
            logger.info(
                "verification cache expired",
                extra={
                    "cache_status": "not_found",
                    "chain_id": chain_id,
                    "code_address": code_address,
                    "code_hash": code_hash,
                },
            )
            return None, False
        raise ValueError(f"unknown source cache status: {row.status}")

    def _negative_is_fresh(self, checked_at: datetime) -> bool:
        age = datetime.utcnow() - checked_at
        return age.total_seconds() <= self.settings.no_source_cache_ttl_seconds

    async def _fetch_verification(
        self,
        chain_id: int,
        address: str,
    ) -> VerificationResult | None:
        failures: list[str] = []
        try:
            sourcify_result = await self._try_sourcify(chain_id, address)
            if sourcify_result:
                return sourcify_result
        except VerificationProviderError as exc:
            failures.extend(exc.errors)

        try:
            etherscan_result = await self._try_etherscan(chain_id, address)
            if etherscan_result:
                return etherscan_result
        except VerificationProviderError as exc:
            failures.extend(exc.errors)

        if failures:
            raise VerificationProviderError(failures)
        return None

    async def _try_sourcify(
        self,
        chain_id: int,
        address: str,
    ) -> VerificationResult | None:
        url = f"https://sourcify.dev/server/v2/contract/{chain_id}/{address}"
        try:
            response = await self.http_client.get(
                url,
                params={"fields": "sources,storageLayout,compilation"},
            )
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise VerificationProviderError(
                    [f"sourcify HTTP {response.status_code}"]
                )

            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            compilation = data.get("compilation") or {}
            if not isinstance(compilation, dict):
                raise ValueError("expected compilation metadata to be an object")
            fully_qualified_name = compilation.get("fullyQualifiedName") or ""
            compilation_target = None
            target_name = None
            if ":" in fully_qualified_name:
                source_path, target_name = fully_qualified_name.rsplit(":", 1)
                compilation_target = {source_path: target_name}

            raw_sources = data.get("sources") or {}
            if not isinstance(raw_sources, dict):
                raise ValueError("expected sources to be an object")
            sources: dict[str, str] = {}
            for filename, source in raw_sources.items():
                if isinstance(source, str):
                    sources[filename] = source
                elif isinstance(source, dict) and isinstance(
                    source.get("content"),
                    str,
                ):
                    sources[filename] = source["content"]

            return VerificationResult(
                source="sourcify",
                match_type=data.get("match") or "unknown",
                name=compilation.get("name") or target_name,
                compilation_target=compilation_target,
                compiler_version=compilation.get("compilerVersion"),
                compiler_settings=compilation.get("compilerSettings"),
                sources=sources or None,
                storage_layout=data.get("storageLayout"),
                language=compilation.get("language") or "Solidity",
            )
        except httpx.RequestError as exc:
            logger.warning("Sourcify request failed: %s", exc)
            raise VerificationProviderError(
                [f"sourcify {type(exc).__name__}"]
            ) from exc
        except (TypeError, ValueError) as exc:
            logger.warning("Invalid Sourcify response for %s: %s", address, exc)
            raise VerificationProviderError(["sourcify invalid response"]) from exc

    async def _try_etherscan(
        self,
        chain_id: int,
        address: str,
    ) -> VerificationResult | None:
        api_key = self.settings.etherscan_keys.get(chain_id)
        base_url = self.settings.etherscan_urls.get(chain_id)
        if not api_key or not base_url:
            return None

        params = {
            "chainid": str(chain_id),
            "module": "contract",
            "action": "getsourcecode",
            "address": address,
            "apikey": api_key,
        }
        try:
            response = await self.http_client.get(base_url, params=params)
            if response.status_code != 200:
                raise VerificationProviderError(
                    [f"etherscan HTTP {response.status_code}"]
                )

            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            if data.get("status") != "1":
                detail = f"{data.get('message', '')} {data.get('result', '')}"
                normalized = detail.lower()
                if "not verified" in normalized or "no data found" in normalized:
                    return None
                raise VerificationProviderError(["etherscan unavailable"])

            results = data.get("result")
            if not isinstance(results, list) or not results:
                raise ValueError("expected a non-empty result list")
            result = results[0]
            if not isinstance(result, dict):
                raise ValueError("expected a result object")
            if not result.get("SourceCode"):
                return None
            return self._parse_etherscan_response(result)
        except httpx.RequestError as exc:
            logger.warning("Etherscan request failed: %s", exc)
            raise VerificationProviderError(
                [f"etherscan {type(exc).__name__}"]
            ) from exc
        except (TypeError, ValueError, KeyError) as exc:
            logger.warning("Invalid Etherscan response for %s: %s", address, exc)
            raise VerificationProviderError(["etherscan invalid response"]) from exc

    @staticmethod
    def _parse_etherscan_response(result: dict) -> VerificationResult:
        source_code = result.get("SourceCode", "")
        contract_name = result.get("ContractName", "")
        compiler_version = result.get("CompilerVersion", "")
        evm_version = result.get("EVMVersion", "")

        is_vyper = "vyper" in compiler_version.lower()
        language = "Vyper" if is_vyper else "Solidity"
        file_extension = ".vy" if is_vyper else ".sol"
        sources = {}
        metadata_settings = {
            "optimizer": {
                "enabled": result.get("OptimizationUsed") == "1",
                "runs": int(result.get("Runs", "200")),
            }
        }
        if evm_version and evm_version != "default":
            metadata_settings["evmVersion"] = evm_version

        if source_code.startswith("{{"):
            try:
                source_code = source_code[1:-1]
                parsed = json.loads(source_code)
                if "sources" in parsed:
                    for filename, content in parsed["sources"].items():
                        sources[filename] = content.get("content", "")
                if "settings" in parsed:
                    metadata_settings.update(parsed["settings"])
            except json.JSONDecodeError:
                sources[f"{contract_name}{file_extension}"] = source_code
        elif source_code.startswith("{"):
            try:
                parsed = json.loads(source_code)
                if "sources" in parsed:
                    for filename, content in parsed["sources"].items():
                        sources[filename] = content.get("content", "")
                if "settings" in parsed:
                    metadata_settings.update(parsed["settings"])
            except json.JSONDecodeError:
                sources[f"{contract_name}{file_extension}"] = source_code
        else:
            sources[f"{contract_name}{file_extension}"] = source_code

        if not is_vyper and any(filename.endswith(".vy") for filename in sources):
            language = "Vyper"

        return VerificationResult(
            source="etherscan",
            match_type="full",
            name=contract_name,
            compilation_target=None,
            compiler_version=compiler_version,
            compiler_settings=metadata_settings,
            sources=sources,
            language=language,
        )
