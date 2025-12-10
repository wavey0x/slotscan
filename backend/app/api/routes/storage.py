"""Storage API routes."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import (
    get_contract_resolver,
    get_layout_parser,
    get_storage_reader,
)
from app.models.api import SlotValueResponse, StorageSnapshotResponse
from app.models.domain import StorageLayout
from app.models.errors import NotAContractError, RPCError
from app.services.layout import LayoutParser
from app.services.resolver import ContractResolver
from app.services.storage import StorageReader

router = APIRouter(prefix="/api/storage", tags=["storage"])


@router.get("/{chain_id}/{address}", response_model=StorageSnapshotResponse)
async def get_storage(
    chain_id: int,
    address: str,
    block: int = Query(..., ge=0, description="Block number"),
    mapping_keys: Optional[str] = Query(
        None, description="JSON-encoded mapping keys: {slot: [keys]}"
    ),
    resolver: ContractResolver = Depends(get_contract_resolver),
    layout_parser: LayoutParser = Depends(get_layout_parser),
    storage_reader: StorageReader = Depends(get_storage_reader),
):
    """
    Get storage snapshot at a block.

    For verified contracts, returns all variables with decoded values.
    For unverified contracts, scans slots 0-256 for non-zero values.
    """
    # Parse mapping keys
    keys_dict = None
    if mapping_keys:
        try:
            keys_dict = json.loads(mapping_keys)
            keys_dict = {int(k): v for k, v in keys_dict.items()}
            # Basic guardrail: limit total mapping keys to avoid huge reads
            total_keys = sum(len(v) for v in keys_dict.values())
            if total_keys > 1000:
                raise ValueError("Too many mapping keys")
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail={"error": "Invalid mapping_keys format", "code": "INVALID_PARAMS"},
            )

    # Resolve contract
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

    # Get layout if verified
    layout = metadata.storage_layout
    if layout and isinstance(layout, dict):
        try:
            layout = StorageLayout.from_dict(layout)
        except Exception:
            layout = None

    if not layout and metadata.is_verified and metadata.sources and metadata.name:
        try:
            layout = await layout_parser.parse(
                contract_name=metadata.name,
                sources=metadata.sources,
                compiler_version=metadata.compiler_version or "0.8.19",
                compiler_settings=metadata.compiler_settings,
                metadata_settings=metadata.compiler_settings,
            )
            metadata.storage_layout = layout
            if resolver.contract_repo:
                await resolver.contract_repo.save(metadata)
        except Exception:
            layout = None

    # Read storage
    try:
        snapshot = await storage_reader.read_at_block(
            chain_id=chain_id,
            address=address,
            block_number=block,
            layout=layout,
            include_mapping_keys=keys_dict,
        )
    except RPCError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": str(e), "code": "RPC_ERROR"},
        )

    return StorageSnapshotResponse(
        chain_id=snapshot.chain_id,
        address=snapshot.address,
        block_number=snapshot.block_number,
        slots=[
            SlotValueResponse(
                slot=s.slot,
                raw_value=s.raw_value,
                variable_name=s.variable.name if s.variable else None,
                variable_path=s.variable_path,
                type_label=s.variable.label if s.variable else None,
                decoded_value=s.decoded_value.decoded if s.decoded_value else None,
                display_value=s.decoded_value.display if s.decoded_value else None,
            )
            for s in snapshot.slots
        ],
        is_complete=snapshot.is_complete,
        is_verified=layout is not None,
        layout_available=layout is not None,
    )


@router.get("/{chain_id}/{address}/slot/{slot}", response_model=SlotValueResponse)
async def get_slot(
    chain_id: int,
    address: str,
    slot: str,
    block: int = Query(..., ge=0, description="Block number"),
    heuristic: bool = Query(False, description="Enable heuristic decode for unverified"),
    resolver: ContractResolver = Depends(get_contract_resolver),
    layout_parser: LayoutParser = Depends(get_layout_parser),
    storage_reader: StorageReader = Depends(get_storage_reader),
):
    """
    Get a single slot value.

    Slot can be provided as hex (0x...) or decimal.
    """
    # Parse slot
    try:
        if slot.startswith("0x"):
            slot_int = int(slot, 16)
        else:
            slot_int = int(slot)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid slot format", "code": "INVALID_SLOT"},
        )

    # Resolve contract
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

    # Get layout
    layout = metadata.storage_layout
    if not layout and metadata.is_verified and metadata.sources and metadata.name:
        try:
            layout = await layout_parser.parse(
                contract_name=metadata.name,
                sources=metadata.sources,
                compiler_version=metadata.compiler_version or "0.8.19",
                compiler_settings=metadata.compiler_settings,
            )
        except Exception:
            layout = None

    # Read slot
    try:
        result = await storage_reader.get_single_slot(
            chain_id=chain_id,
            address=address,
            slot=slot_int,
            block_number=block,
            layout=layout,
            use_heuristic_unverified=heuristic,
        )
    except RPCError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": str(e), "code": "RPC_ERROR"},
        )

    return SlotValueResponse(
        slot=hex(slot_int),
        raw_value=result.raw_value,
        variable_name=result.variable.name if result.variable else None,
        variable_path=result.variable_path,
        type_label=result.variable.label if result.variable else None,
        decoded_value=result.decoded_value.decoded if result.decoded_value else None,
        display_value=result.decoded_value.display if result.decoded_value else None,
    )
