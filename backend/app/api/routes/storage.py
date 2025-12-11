"""Storage API routes."""

import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import (
    get_contract_resolver,
    get_layout_parser,
    get_storage_reader,
    get_web3_provider,
)
from app.services.web3_provider import Web3Provider
from app.models.api import SlotValueResponse, StorageSnapshotResponse
from app.models.domain import StorageLayout
from app.models.errors import NotAContractError, RPCError
from app.services.layout import LayoutParser
from app.services.resolver import ContractResolver
from app.services.storage import StorageReader
from app.utils.type_labels import normalize_contract_label

router = APIRouter(prefix="/api/slotscan/storage", tags=["storage"])


def _get_type_label(
    variable, layout: StorageLayout | None, variable_path: str | None = None
) -> str | None:
    """Get display type label for a variable, normalizing contract types to address.

    For array element lookups (variable_path like "arr[0]"), returns the element type
    instead of the array type.
    """
    if not variable:
        return None

    label = variable.label
    kind = None

    # Look up the type to get its kind
    if layout:
        var_type = layout.get_type(variable.type_id)
        if var_type:
            kind = var_type.kind

            # Check if this is an array element lookup
            if variable_path and var_type.array_length and var_type.element_type:
                # Check if path indicates an element (e.g., "arr[0]" not just "arr")
                if re.search(r'\[\d+\]$', variable_path):
                    # It's an array element lookup - use element type
                    element_type = layout.get_type(var_type.element_type)
                    if element_type:
                        label = element_type.label
                        kind = element_type.kind

    return normalize_contract_label(label, kind)


@router.get("/{chain_id}/{address}", response_model=StorageSnapshotResponse)
async def get_storage(
    chain_id: int,
    address: str,
    block: str = Query(..., description="Block number or 'latest'"),
    mapping_keys: Optional[str] = Query(
        None, description="JSON-encoded mapping keys: {slot: [keys]}"
    ),
    resolver: ContractResolver = Depends(get_contract_resolver),
    layout_parser: LayoutParser = Depends(get_layout_parser),
    storage_reader: StorageReader = Depends(get_storage_reader),
    web3_provider: Web3Provider = Depends(get_web3_provider),
):
    """
    Get storage snapshot at a block.

    For verified contracts, returns all variables with decoded values.
    For unverified contracts, scans slots 0-256 for non-zero values.
    """
    # Parse block parameter
    use_latest = block.lower() == "latest"
    if use_latest:
        # Resolve "latest" to actual block number for the response
        try:
            web3 = web3_provider.get_web3(chain_id)
            block_number = await web3.eth.get_block_number()
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail={"error": f"Failed to get latest block: {e}", "code": "RPC_ERROR"},
            )
    else:
        try:
            block_number = int(block)
            if block_number < 0:
                raise ValueError()
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error": "Invalid block format", "code": "INVALID_BLOCK"},
            )

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
            block_number=block_number,
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
                value_encoded=s.raw_value,
                value_decoded=s.decoded_value.decoded if s.decoded_value else None,
                variable_name=s.variable.name if s.variable else None,
                variable_path=s.variable_path,
                type_label=_get_type_label(s.variable, layout, s.variable_path),
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
    block: str = Query(..., description="Block number or 'latest'"),
    heuristic: bool = Query(False, description="Enable heuristic decode for unverified"),
    resolver: ContractResolver = Depends(get_contract_resolver),
    layout_parser: LayoutParser = Depends(get_layout_parser),
    storage_reader: StorageReader = Depends(get_storage_reader),
):
    """
    Get a single slot value.

    Slot can be provided as hex (0x...) or decimal.
    Block can be a number or 'latest'.
    """
    # Parse block
    if block.lower() == "latest":
        block_number = "latest"
    else:
        try:
            block_number = int(block)
            if block_number < 0:
                raise ValueError()
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error": "Invalid block format", "code": "INVALID_BLOCK"},
            )
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
        value_encoded=result.raw_value,
        value_decoded=result.decoded_value.decoded if result.decoded_value else None,
        variable_name=result.variable.name if result.variable else None,
        variable_path=result.variable_path,
        type_label=_get_type_label(result.variable, layout, result.variable_path),
    )
