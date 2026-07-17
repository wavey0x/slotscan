"""Address, exact-block, and subject orchestration for comparisons."""

from __future__ import annotations

import logging
import re
from time import perf_counter

from web3 import Web3

from app.models.errors import NotAContractError
from app.services.layout_compatibility.compare import LayoutComparator
from app.services.layout_compatibility.models import (
    ComparisonVerdict,
    LayoutComparisonReport,
    ResolvedLayoutSubject,
)
from app.services.layout_compatibility.normalize import (
    LayoutNormalizationUnavailable,
    LayoutNormalizer,
)
from app.services.storage_view import StorageContext, StorageViewService
from app.services.web3_provider import StorageAttempt, Web3Provider

logger = logging.getLogger(__name__)


class LayoutComparisonService:
    """Resolve both sides sequentially and invoke the pure comparator."""

    def __init__(
        self,
        *,
        web3_provider: Web3Provider,
        storage_view_service: StorageViewService,
        normalizer: LayoutNormalizer,
        comparator: LayoutComparator,
    ):
        self.web3_provider = web3_provider
        self.storage_view_service = storage_view_service
        self.normalizer = normalizer
        self.comparator = comparator

    async def compare(
        self,
        *,
        chain_id: int,
        from_address: str,
        to_address: str,
        from_block: int | None = None,
        from_block_hash: str | None = None,
        to_block: int | None = None,
        to_block_hash: str | None = None,
    ) -> LayoutComparisonReport:
        started = perf_counter()
        self._validate_exact_ref(from_block, from_block_hash, "from")
        self._validate_exact_ref(to_block, to_block_hash, "to")
        attempts: dict[tuple[int | str, str | None], StorageAttempt] = {}

        async def attempt_for(
            number: int | None,
            block_hash: str | None,
        ) -> StorageAttempt:
            key = (
                number if number is not None else "latest",
                block_hash.lower() if block_hash else None,
            )
            if key not in attempts:
                if number is not None and block_hash:
                    attempts[key] = (
                        await self.web3_provider.create_exact_storage_attempt(
                            chain_id,
                            number,
                            block_hash,
                        )
                    )
                else:
                    attempts[key] = await self.web3_provider.create_storage_attempt(
                        chain_id,
                        number if number is not None else "latest",
                    )
            return attempts[key]

        from_attempt = await attempt_for(from_block, from_block_hash)
        to_attempt = await attempt_for(to_block, to_block_hash)
        resolution_started = perf_counter()
        from_subject = await self._prepare_subject(
            from_attempt,
            from_address,
        )
        to_subject = await self._prepare_subject(
            to_attempt,
            to_address,
        )
        resolution_ms = (perf_counter() - resolution_started) * 1000

        limitations = tuple(
            code
            for code in (
                self._subject_limitation("from", from_subject),
                self._subject_limitation("to", to_subject),
            )
            if code
        )
        normalization_ms = 0.0
        comparison_ms = 0.0
        if limitations:
            report = LayoutComparisonReport(
                chain_id=chain_id,
                verdict=ComparisonVerdict.UNAVAILABLE,
                from_subject=from_subject,
                to_subject=to_subject,
                summary=None,
                entries=(),
                limitations=limitations,
            )
        else:
            normalization_started = perf_counter()
            try:
                normalized_from = self.normalizer.normalize(from_subject.layout)
                normalized_to = self.normalizer.normalize(to_subject.layout)
            except LayoutNormalizationUnavailable as exc:
                report = LayoutComparisonReport(
                    chain_id=chain_id,
                    verdict=ComparisonVerdict.UNAVAILABLE,
                    from_subject=from_subject,
                    to_subject=to_subject,
                    summary=None,
                    entries=(),
                    limitations=(exc.code,),
                )
            else:
                normalization_ms = (
                    perf_counter() - normalization_started
                ) * 1000
                comparison_started = perf_counter()
                result = self.comparator.compare_normalized(
                    normalized_from,
                    normalized_to,
                )
                comparison_ms = (perf_counter() - comparison_started) * 1000
                report = LayoutComparisonReport(
                    chain_id=chain_id,
                    verdict=result.verdict,
                    from_subject=from_subject,
                    to_subject=to_subject,
                    summary=result.summary,
                    entries=result.entries,
                    limitations=result.limitations,
                )

        logger.info(
            "layout_comparison chain_id=%s verdict=%s limitations=%s "
            "resolution_ms=%.2f normalization_ms=%.2f comparison_ms=%.2f "
            "total_ms=%.2f",
            chain_id,
            report.verdict.value,
            ",".join(report.limitations) or "none",
            resolution_ms,
            normalization_ms,
            comparison_ms,
            (perf_counter() - started) * 1000,
        )
        return report

    @staticmethod
    def _validate_exact_ref(
        number: int | None,
        block_hash: str | None,
        side: str,
    ) -> None:
        if number is not None and number < 0:
            raise ValueError(f"{side}_block cannot be negative")
        if block_hash and number is None:
            raise ValueError(
                f"{side}_block_hash requires {side}_block"
            )
        if block_hash and not re.fullmatch(
            r"0x[0-9a-fA-F]{64}",
            block_hash,
        ):
            raise ValueError(
                f"{side}_block_hash must be a 32-byte hex value"
            )

    async def _prepare_subject(
        self,
        attempt: StorageAttempt,
        address: str,
    ) -> ResolvedLayoutSubject:
        checksum = Web3.to_checksum_address(address)
        try:
            context = await self.storage_view_service.prepare_on_attempt(
                attempt,
                checksum,
            )
        except NotAContractError:
            return ResolvedLayoutSubject(
                input_address=checksum,
                storage_address=checksum,
                code_address=checksum,
                kind="direct",
                block_number=attempt.block_ref.number,
                block_hash=attempt.block_ref.hash,
                name=None,
                layout_status="not_contract",
                layout=None,
            )
        return self._subject_from_context(context, checksum)

    def _subject_from_context(
        self,
        context: StorageContext,
        input_address: str,
    ) -> ResolvedLayoutSubject:
        metadata = context.metadata
        if metadata.is_delegated:
            kind = "eip7702"
            code_address = metadata.delegate_address or input_address
        elif metadata.is_proxy:
            kind = "proxy"
            code_address = metadata.implementation_address or input_address
        else:
            kind = "direct"
            code_address = metadata.address
        layout_status = context.layout_status
        if metadata.delegation_status == "empty":
            layout_status = "not_contract"
        elif metadata.delegation_status == "nested":
            layout_status = "unsupported"
        elif context.layout is not None:
            limitation = self.normalizer.exact_limitation(context.layout)
            if limitation == "non_exact_layout":
                layout_status = "non_exact"
            elif limitation:
                layout_status = "unsupported"
            else:
                layout_status = "ok"
        return ResolvedLayoutSubject(
            input_address=Web3.to_checksum_address(input_address),
            storage_address=Web3.to_checksum_address(metadata.address),
            code_address=Web3.to_checksum_address(code_address),
            kind=kind,
            block_number=context.attempt.block_ref.number,
            block_hash=context.attempt.block_ref.hash,
            name=metadata.name,
            layout_status=layout_status,
            layout=context.layout,
        )

    @staticmethod
    def _subject_limitation(
        side: str,
        subject: ResolvedLayoutSubject,
    ) -> str | None:
        if subject.layout_status == "ok":
            return None
        return f"{side}_{subject.layout_status}"
