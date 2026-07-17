"""Exact directional storage-layout comparison API."""

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from web3 import Web3

from app.api.dependencies import get_layout_comparison_service
from app.models.api import LayoutComparisonResponse
from app.services.layout_compatibility.service import LayoutComparisonService

router = APIRouter(
    prefix="/api/slotscan/layout-comparisons",
    tags=["layout-comparisons"],
)
BLOCK_HASH_PATTERN = re.compile(r"0x[0-9a-fA-F]{64}")


@router.get("/{chain_id}", response_model=LayoutComparisonResponse)
async def get_layout_comparison(
    chain_id: str,
    from_address: str | None = Query(None),
    to_address: str | None = Query(None),
    from_block: str | None = Query(None),
    from_block_hash: str | None = Query(None),
    to_block: str | None = Query(None),
    to_block_hash: str | None = Query(None),
    service: LayoutComparisonService = Depends(
        get_layout_comparison_service
    ),
):
    try:
        parsed_chain_id = int(chain_id, 10)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid chain id", "code": "INVALID_CHAIN"},
        ) from exc
    if parsed_chain_id != 1:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Only Ethereum mainnet is supported",
                "code": "INVALID_CHAIN",
            },
        )
    try:
        if not from_address or not to_address:
            raise ValueError("Both comparison addresses are required")
        checksum_from = Web3.to_checksum_address(from_address)
        checksum_to = Web3.to_checksum_address(to_address)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid comparison address",
                "code": "INVALID_ADDRESS",
            },
        ) from exc
    try:
        parsed_from_block = (
            int(from_block, 10) if from_block is not None else None
        )
        parsed_to_block = (
            int(to_block, 10) if to_block is not None else None
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Block selectors must be decimal integers",
                "code": "INVALID_BLOCK",
            },
        ) from exc
    if parsed_from_block is not None and parsed_from_block < 0:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "from_block cannot be negative",
                "code": "INVALID_BLOCK",
            },
        )
    if parsed_to_block is not None and parsed_to_block < 0:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "to_block cannot be negative",
                "code": "INVALID_BLOCK",
            },
        )
    if from_block_hash and parsed_from_block is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "from_block_hash requires from_block",
                "code": "INVALID_BLOCK",
            },
        )
    if to_block_hash and parsed_to_block is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "to_block_hash requires to_block",
                "code": "INVALID_BLOCK",
            },
        )
    if (
        from_block_hash
        and BLOCK_HASH_PATTERN.fullmatch(from_block_hash) is None
    ) or (
        to_block_hash
        and BLOCK_HASH_PATTERN.fullmatch(to_block_hash) is None
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Block hashes must be 32-byte hex values",
                "code": "INVALID_BLOCK",
            },
        )
    try:
        report = await service.compare(
            chain_id=parsed_chain_id,
            from_address=checksum_from,
            to_address=checksum_to,
            from_block=parsed_from_block,
            from_block_hash=from_block_hash,
            to_block=parsed_to_block,
            to_block_hash=to_block_hash,
        )
        return report.to_wire()
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": str(exc), "code": "INVALID_BLOCK"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Upstream service unavailable",
                "code": "UPSTREAM_FAILURE",
            },
        ) from exc
