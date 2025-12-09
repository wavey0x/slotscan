"""Contract API routes."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import (
    get_contract_resolver,
    get_layout_parser,
)
from app.models.api import (
    ContractResponse,
    StorageLayoutResponse,
    StorageTypeResponse,
    StorageVariableResponse,
)
from app.models.domain import StorageLayout
from app.models.errors import NotAContractError, RPCError
from app.services.layout import LayoutParser
from app.services.resolver import ContractResolver

router = APIRouter(prefix="/api/storagescan/contracts", tags=["contracts"])


@router.get("/{chain_id}/{address}", response_model=ContractResponse)
async def get_contract(
    chain_id: int,
    address: str,
    resolver: ContractResolver = Depends(get_contract_resolver),
    layout_parser: LayoutParser = Depends(get_layout_parser),
):
    """
    Get contract metadata.

    Returns proxy info, verification status, and whether layout is available.
    """
    try:
        metadata = await resolver.resolve(chain_id, address)
    except NotAContractError:
        raise HTTPException(
            status_code=404,
            detail={"error": "Not a contract", "code": "NOT_CONTRACT"},
        )
    except RPCError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": str(e), "code": "RPC_ERROR"},
        )

    # Try to parse layout if verified and we have sources
    has_layout = False

    if metadata.storage_layout and isinstance(metadata.storage_layout, StorageLayout):
        has_layout = True
    elif metadata.storage_layout and isinstance(metadata.storage_layout, dict):
        try:
            metadata.storage_layout = StorageLayout.from_dict(metadata.storage_layout)
            has_layout = True
        except Exception:
            has_layout = False

    if not has_layout and metadata.is_verified and metadata.sources and metadata.name:
        try:
            layout = await layout_parser.parse(
                contract_name=metadata.name,
                sources=metadata.sources,
                compiler_version=metadata.compiler_version or "0.8.19",
                compiler_settings=metadata.compiler_settings,
                metadata_settings=metadata.compiler_settings,
            )
            metadata.storage_layout = layout
            has_layout = True
            if resolver.contract_repo:
                await resolver.contract_repo.save(metadata)
        except Exception:
            has_layout = False

    return ContractResponse(
        chain_id=metadata.chain_id,
        address=metadata.address,
        name=metadata.name,
        code_hash=metadata.code_hash,
        is_proxy=metadata.is_proxy,
        proxy_type=metadata.proxy_type,
        implementation_address=metadata.implementation_address,
        is_verified=metadata.is_verified,
        verification_source=metadata.verification_source,
        compiler_version=metadata.compiler_version,
        has_layout=has_layout,
    )


@router.get("/{chain_id}/{address}/layout", response_model=StorageLayoutResponse)
async def get_layout(
    chain_id: int,
    address: str,
    resolver: ContractResolver = Depends(get_contract_resolver),
    layout_parser: LayoutParser = Depends(get_layout_parser),
):
    """
    Get storage layout for a verified contract.

    Returns 404 if contract is not verified or layout unavailable.
    """
    try:
        metadata = await resolver.resolve(chain_id, address)
    except NotAContractError:
        raise HTTPException(
            status_code=404,
            detail={"error": "Not a contract", "code": "NOT_CONTRACT"},
        )
    except RPCError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": str(e), "code": "RPC_ERROR"},
        )

    layout = metadata.storage_layout

    # Try to parse if not cached
    if not layout and metadata.is_verified and metadata.sources and metadata.name:
        try:
            layout = await layout_parser.parse(
                contract_name=metadata.name,
                sources=metadata.sources,
                compiler_version=metadata.compiler_version or "0.8.19",
                compiler_settings=metadata.compiler_settings,
            )
        except Exception as e:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": f"Layout parsing failed: {e}",
                    "code": "LAYOUT_PARSE_ERROR",
                },
            )

    if not layout:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "Contract not verified or layout unavailable",
                "code": "NO_LAYOUT",
            },
        )

    return StorageLayoutResponse(
        contract_name=layout.contract_name,
        variables=[
            StorageVariableResponse(
                name=v.name,
                slot=v.slot,
                offset=v.offset,
                size=v.size,
                type_id=v.type_id,
                type_label=v.label,
            )
            for v in layout.variables
        ],
        types={
            tid: StorageTypeResponse(
                id=t.id,
                label=t.label,
                kind=t.kind,
                encoding=t.encoding,
                num_bytes=t.num_bytes,
                element_type=t.element_type,
                array_length=t.array_length,
                key_type=t.key_type,
                value_type=t.value_type,
            )
            for tid, t in layout.types.items()
        },
    )
