"""Backend-authoritative typed storage query route."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_storage_view_service
from app.models.api import StorageQueryRequest, StorageQueryResponse
from app.models.errors import NotAContractError
from app.services.storage_view import StorageQueryError, StorageViewService

router = APIRouter(prefix="/api/slotscan/storage", tags=["storage"])


@router.post("/query", response_model=StorageQueryResponse)
async def query_storage(
    request: StorageQueryRequest,
    service: StorageViewService = Depends(get_storage_view_service),
):
    """Resolve and materialize one identity-bound typed storage access."""
    try:
        chain_id = int(request.chain_id, 0)
        block_number = int(request.block_ref.number, 0)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "chain_id and block_ref.number must be integer strings",
                "code": "INVALID_INPUT",
            },
        ) from exc

    try:
        return await service.query(
            chain_id=chain_id,
            address=request.address,
            block_number=block_number,
            block_hash=request.block_ref.hash,
            layout_id=request.layout_id,
            declaration_id=request.access.declaration_id,
            steps=[step.model_dump() for step in request.access.steps],
        )
    except StorageQueryError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": str(exc), "code": exc.code},
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
