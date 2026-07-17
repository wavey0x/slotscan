"""Contract storage-view API route."""

from fastapi import APIRouter, Depends, HTTPException, Query
from web3 import Web3

from app.api.dependencies import get_storage_view_service
from app.models.api import StorageViewResponse
from app.models.errors import NotAContractError
from app.services.storage_view import StorageViewService

router = APIRouter(prefix="/api/slotscan/contracts", tags=["contracts"])


@router.get(
    "/{chain_id}/{address}/storage-view",
    response_model=StorageViewResponse,
)
async def get_storage_view(
    chain_id: int,
    address: str,
    block: str = Query("latest", description="latest, safe, finalized, or exact block"),
    service: StorageViewService = Depends(get_storage_view_service),
):
    """Return metadata, immutable layout, and scalar values at one exact block."""
    if chain_id <= 0:
        raise HTTPException(
            status_code=400,
            detail={"error": "chain_id must be positive", "code": "INVALID_CHAIN"},
        )
    try:
        checksum_address = Web3.to_checksum_address(address)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid contract address", "code": "INVALID_ADDRESS"},
        ) from exc
    try:
        return await service.get_view(chain_id, checksum_address, block)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": str(exc), "code": "INVALID_BLOCK"},
        ) from exc
    except NotAContractError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": str(exc), "code": "NOT_CONTRACT"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "code": "RPC_ERROR"},
        ) from exc
