use alloy_primitives::{Address, B256, Bytes, U256};
use alloy_rpc_types_trace::geth::{AccountState, PreStateFrame};
use async_trait::async_trait;
use jsonrpsee::{
    core::RpcResult,
    proc_macros::rpc,
    types::{ErrorObjectOwned, error::INVALID_PARAMS_CODE},
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

pub const MAX_STEPS: u64 = 5_000_000;
pub const MAX_WRITES: usize = 10_000;
pub const MAX_SHA3_OPERATIONS: usize = 20_000;
pub const MAX_PREIMAGE_BYTES: usize = 5 * 1024 * 1024;
pub const MAX_OBSERVED_STORAGE: usize = 100_000;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TraceLimits {
    pub max_steps: u64,
    pub max_writes: usize,
    pub max_sha3_operations: usize,
    pub max_preimage_bytes: usize,
    pub max_observed_storage: usize,
}

impl TraceLimits {
    pub fn validate(self) -> Result<Self, ErrorObjectOwned> {
        let valid = self.max_steps <= MAX_STEPS
            && self.max_writes <= MAX_WRITES
            && self.max_sha3_operations <= MAX_SHA3_OPERATIONS
            && self.max_preimage_bytes <= MAX_PREIMAGE_BYTES
            && self.max_observed_storage <= MAX_OBSERVED_STORAGE;
        if valid {
            Ok(self)
        } else {
            Err(ErrorObjectOwned::owned(
                INVALID_PARAMS_CODE,
                "trace limits exceed the supported maximum",
                None::<()>,
            ))
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CodeAttribution {
    Exact,
    Unknown,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum CodeSource {
    Direct,
    Eip7702,
    Unknown,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub enum WriteOpcode {
    #[serde(rename = "SSTORE")]
    Sstore,
    #[serde(rename = "TSTORE")]
    Tstore,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum StorageNamespace {
    Persistent,
    Transient,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WriteEvidence {
    pub address: Address,
    pub code_address: Option<Address>,
    pub code_attribution: CodeAttribution,
    pub code_source: CodeSource,
    pub code_designator: Option<String>,
    pub pc: u64,
    pub slot: B256,
    pub old_value: Option<B256>,
    pub value: B256,
    pub opcode: WriteOpcode,
    pub namespace: StorageNamespace,
    pub depth: u64,
    pub index: u64,
    pub frame_id: u64,
    pub frame_parent_id: Option<u64>,
    pub frame_failed: bool,
    pub frame_reverted: bool,
    pub rollback_frame_id: Option<u64>,
    pub rollback_parent_id: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Sha3Evidence {
    pub address: Address,
    pub preimage: alloy_primitives::Bytes,
    pub size: usize,
    pub depth: u64,
}

pub type ObservedStorage = BTreeMap<Address, BTreeMap<B256, Option<B256>>>;

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PrestateAccount {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub balance: Option<U256>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub code: Option<Bytes>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub nonce: Option<u64>,
    pub storage: BTreeMap<B256, B256>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
pub struct PrestateDiff {
    pub post: BTreeMap<Address, PrestateAccount>,
    pub pre: BTreeMap<Address, PrestateAccount>,
}

impl TryFrom<PreStateFrame> for PrestateDiff {
    type Error = NativeTraceError;

    fn try_from(frame: PreStateFrame) -> Result<Self, Self::Error> {
        let PreStateFrame::Diff(diff) = frame else {
            return Err(NativeTraceError::Internal);
        };
        let convert = |accounts: BTreeMap<Address, AccountState>| {
            accounts
                .into_iter()
                .map(|(address, account)| {
                    (
                        address,
                        PrestateAccount {
                            balance: account.balance,
                            code: account.code,
                            nonce: account.nonce,
                            storage: account.storage,
                        },
                    )
                })
                .collect()
        };
        Ok(Self {
            post: convert(diff.post),
            pre: convert(diff.pre),
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DegradedReason {
    TraceLimit,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TraceResponse {
    pub transaction_hash: B256,
    pub block_hash: B256,
    pub transaction_index: u64,
    pub root_succeeded: bool,
    pub prestate_diff: PrestateDiff,
    pub writes: Vec<WriteEvidence>,
    pub sha3_operations: Vec<Sha3Evidence>,
    pub observed_storage: ObservedStorage,
    pub observed_storage_complete: bool,
    pub step_count: u64,
    pub degraded_reason: Option<DegradedReason>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NativeTraceError {
    Internal,
}

#[async_trait]
pub trait NativeTrace: Clone + Send + Sync + 'static {
    async fn trace_transaction(
        &self,
        tx_hash: B256,
        limits: TraceLimits,
    ) -> Result<Option<TraceResponse>, NativeTraceError>;
}

#[rpc(server, namespace = "slotscan")]
pub trait SlotScanApi {
    #[method(name = "traceTransaction")]
    async fn trace_transaction(
        &self,
        tx_hash: B256,
        limits: TraceLimits,
    ) -> RpcResult<TraceResponse>;
}

#[derive(Clone)]
pub struct SlotScanRpc<T> {
    tracer: T,
}

impl<T> SlotScanRpc<T> {
    pub const fn new(tracer: T) -> Self {
        Self { tracer }
    }
}

#[async_trait]
impl<T> SlotScanApiServer for SlotScanRpc<T>
where
    T: NativeTrace,
{
    async fn trace_transaction(
        &self,
        tx_hash: B256,
        limits: TraceLimits,
    ) -> RpcResult<TraceResponse> {
        let limits = limits.validate()?;
        match self.tracer.trace_transaction(tx_hash, limits).await {
            Ok(Some(trace)) => Ok(trace),
            Ok(None) => Err(ErrorObjectOwned::owned(
                -32000,
                "transaction not found",
                None::<()>,
            )),
            Err(NativeTraceError::Internal) => Err(ErrorObjectOwned::owned(
                -32603,
                "internal error",
                None::<()>,
            )),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[derive(Clone)]
    struct FakeTrace;

    #[async_trait]
    impl NativeTrace for FakeTrace {
        async fn trace_transaction(
            &self,
            tx_hash: B256,
            _limits: TraceLimits,
        ) -> Result<Option<TraceResponse>, NativeTraceError> {
            Ok(Some(TraceResponse {
                transaction_hash: tx_hash,
                block_hash: B256::repeat_byte(0x22),
                transaction_index: 3,
                root_succeeded: true,
                prestate_diff: PrestateDiff::default(),
                writes: Vec::new(),
                sha3_operations: Vec::new(),
                observed_storage: BTreeMap::new(),
                observed_storage_complete: true,
                step_count: 1,
                degraded_reason: None,
            }))
        }
    }

    fn limits_json() -> &'static str {
        r#"{
            "maxSteps": 10,
            "maxWrites": 10,
            "maxSha3Operations": 10,
            "maxPreimageBytes": 1024,
            "maxObservedStorage": 10
        }"#
    }

    #[tokio::test]
    async fn registers_only_the_slotscan_method() {
        let module = SlotScanRpc::new(FakeTrace).into_rpc();
        let methods: Vec<_> = module.method_names().collect();
        assert_eq!(methods, ["slotscan_traceTransaction"]);

        let hash = B256::repeat_byte(0x11);
        let request = format!(
            r#"{{"jsonrpc":"2.0","id":1,"method":"slotscan_traceTransaction","params":["{hash}",{}]}}"#,
            limits_json()
        );
        let (response, _) = module.raw_json_request(&request, 1).await.unwrap();
        assert!(response.get().contains(r#""transactionIndex":3"#));

        let (missing, _) = module
            .raw_json_request(
                r#"{"jsonrpc":"2.0","id":2,"method":"slotscan_unknown","params":[]}"#,
                1,
            )
            .await
            .unwrap();
        assert!(missing.get().contains(r#""code":-32601"#));
    }

    #[test]
    fn rejects_limits_above_every_hard_ceiling() {
        let base = TraceLimits {
            max_steps: MAX_STEPS,
            max_writes: MAX_WRITES,
            max_sha3_operations: MAX_SHA3_OPERATIONS,
            max_preimage_bytes: MAX_PREIMAGE_BYTES,
            max_observed_storage: MAX_OBSERVED_STORAGE,
        };
        assert!(base.validate().is_ok());

        for invalid in [
            TraceLimits {
                max_steps: MAX_STEPS + 1,
                ..base
            },
            TraceLimits {
                max_writes: MAX_WRITES + 1,
                ..base
            },
            TraceLimits {
                max_sha3_operations: MAX_SHA3_OPERATIONS + 1,
                ..base
            },
            TraceLimits {
                max_preimage_bytes: MAX_PREIMAGE_BYTES + 1,
                ..base
            },
            TraceLimits {
                max_observed_storage: MAX_OBSERVED_STORAGE + 1,
                ..base
            },
        ] {
            assert!(invalid.validate().is_err());
        }
    }

    #[test]
    fn owned_prestate_accounts_keep_empty_storage_for_diff_parity() {
        let encoded = serde_json::to_value(PrestateAccount::default()).unwrap();
        assert_eq!(encoded, serde_json::json!({"storage": {}}));
    }
}
