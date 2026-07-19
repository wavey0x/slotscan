use crate::{
    inspector::SlotScanInspector,
    rpc::{
        NativeTrace, NativeTraceError, ObservedStorage, PrestateDiff, TraceLimits, TraceResponse,
    },
};
use alloy_primitives::B256;
use alloy_rpc_types_trace::geth::PreStateConfig;
use async_trait::async_trait;
use reth_ethereum::evm::revm::revm::database_interface::Database;
use reth_rpc_eth_api::{FromEthApiError, helpers::TraceExt};
use revm_inspectors::tracing::GethTraceBuilder;
use std::{collections::BTreeMap, fmt::Display};

#[derive(Clone)]
pub struct RethTraceAdapter<Eth> {
    eth_api: Eth,
}

impl<Eth> RethTraceAdapter<Eth> {
    pub const fn new(eth_api: Eth) -> Self {
        Self { eth_api }
    }
}

struct ReplayOutput {
    transaction_hash: B256,
    block_hash: Option<B256>,
    transaction_index: Option<u64>,
    root_succeeded: bool,
    prestate_diff: alloy_rpc_types_trace::geth::PreStateFrame,
    inspector: SlotScanInspector,
    observed_storage: ObservedStorage,
    observed_storage_complete: bool,
}

#[async_trait]
impl<Eth> NativeTrace for RethTraceAdapter<Eth>
where
    Eth: TraceExt + Clone + Send + Sync + 'static,
    Eth::Error: Display,
{
    async fn trace_transaction(
        &self,
        tx_hash: B256,
        limits: TraceLimits,
    ) -> Result<Option<TraceResponse>, NativeTraceError> {
        let _permit = self
            .eth_api
            .acquire_owned_tracing()
            .await
            .map_err(|_| NativeTraceError::Internal)?;

        let replay = self
            .eth_api
            .spawn_trace_transaction_in_block_with_inspector(
                tx_hash,
                SlotScanInspector::new(limits),
                move |tx_info, inspector, result, mut db| {
                    let root_succeeded = result.result.is_success();
                    let (observation_keys, mut observed_storage_complete) =
                        inspector.observation_keys();
                    let mut observed_storage = BTreeMap::new();
                    for key in observation_keys {
                        let value = match db.storage(key.address, key.slot) {
                            Ok(value) => Some(B256::new(value.to_be_bytes())),
                            Err(_) => {
                                observed_storage_complete = false;
                                None
                            }
                        };
                        observed_storage
                            .entry(key.address)
                            .or_insert_with(BTreeMap::new)
                            .insert(B256::new(key.slot.to_be_bytes()), value);
                    }

                    let prestate_diff = GethTraceBuilder::new(Vec::new())
                        .geth_prestate_traces(
                            &result,
                            &PreStateConfig {
                                diff_mode: Some(true),
                                ..Default::default()
                            },
                            &mut db,
                        )
                        .map_err(Eth::Error::from_eth_err)?;

                    Ok(ReplayOutput {
                        transaction_hash: tx_info.hash.unwrap_or(tx_hash),
                        block_hash: tx_info.block_hash,
                        transaction_index: tx_info.index,
                        root_succeeded,
                        prestate_diff,
                        inspector,
                        observed_storage,
                        observed_storage_complete,
                    })
                },
            )
            .await
            .map_err(|_| NativeTraceError::Internal)?;

        let Some(replay) = replay else {
            return Ok(None);
        };
        let block_hash = replay.block_hash.ok_or(NativeTraceError::Internal)?;
        let transaction_index = replay.transaction_index.ok_or(NativeTraceError::Internal)?;
        let prestate_diff = PrestateDiff::try_from(replay.prestate_diff)?;
        let step_count = replay.inspector.step_count();
        let degraded_reason = replay.inspector.degraded_reason();
        let (writes, sha3_operations) = replay.inspector.into_details();

        Ok(Some(TraceResponse {
            transaction_hash: replay.transaction_hash,
            block_hash,
            transaction_index,
            root_succeeded: replay.root_succeeded,
            prestate_diff,
            writes,
            sha3_operations,
            observed_storage: replay.observed_storage,
            observed_storage_complete: replay.observed_storage_complete,
            step_count,
            degraded_reason,
        }))
    }
}
