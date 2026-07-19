use crate::rpc::{
    CodeAttribution, CodeSource, DegradedReason, Sha3Evidence, StorageNamespace, TraceLimits,
    WriteEvidence, WriteOpcode,
};
use alloy_primitives::{Address, B256, Bytes, U256};
use reth_ethereum::evm::revm::revm::{
    bytecode::{Bytecode, opcode},
    context::JournalEntry,
    context_interface::{ContextTr, JournalTr},
    inspector::{Inspector, JournalExt},
    interpreter::{
        CallInputs, CallOutcome, CreateInputs, CreateOutcome, Interpreter, InterpreterAction,
        interpreter::EthInterpreter,
        interpreter_types::{Jumps, LoopControl, MemoryTr},
    },
};
use std::collections::HashSet;

#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct ObservationKey {
    pub address: Address,
    pub slot: U256,
}

#[derive(Clone, Debug)]
struct ActiveFrame {
    id: u64,
    parent_id: Option<u64>,
    first_write_index: usize,
    storage_address: Address,
    requested_code_address: Address,
    code_address: Option<Address>,
    code_attribution: CodeAttribution,
    code_source: CodeSource,
    code_designator: Option<String>,
}

#[derive(Clone, Debug)]
struct PendingWrite {
    address: Address,
    code_address: Option<Address>,
    code_attribution: CodeAttribution,
    code_source: CodeSource,
    code_designator: Option<String>,
    pc: u64,
    slot: U256,
    value: U256,
    opcode: WriteOpcode,
    namespace: StorageNamespace,
    depth: u64,
    index: u64,
    frame_id: u64,
    frame_parent_id: Option<u64>,
    journal_len: usize,
}

#[derive(Clone, Copy, Debug)]
struct PendingSha3 {
    address: Address,
    offset: usize,
    size: usize,
    depth: u64,
}

#[derive(Clone, Debug)]
pub struct SlotScanInspector {
    limits: TraceLimits,
    step_count: u64,
    writes: Vec<WriteEvidence>,
    sha3_operations: Vec<Sha3Evidence>,
    sha3_bytes: usize,
    active_frames: Vec<ActiveFrame>,
    next_frame_id: u64,
    pending_write: Option<PendingWrite>,
    pending_sha3: Option<PendingSha3>,
    sload_keys: Vec<ObservationKey>,
    sload_key_set: HashSet<ObservationKey>,
    observation_overflow: bool,
    degraded_reason: Option<DegradedReason>,
}

impl SlotScanInspector {
    pub fn new(limits: TraceLimits) -> Self {
        Self {
            limits,
            step_count: 0,
            writes: Vec::with_capacity(limits.max_writes.min(1_024)),
            sha3_operations: Vec::with_capacity(limits.max_sha3_operations.min(1_024)),
            sha3_bytes: 0,
            active_frames: Vec::with_capacity(16),
            next_frame_id: 0,
            pending_write: None,
            pending_sha3: None,
            sload_keys: Vec::with_capacity(limits.max_observed_storage.min(1_024)),
            sload_key_set: HashSet::with_capacity(limits.max_observed_storage.min(1_024)),
            observation_overflow: false,
            degraded_reason: None,
        }
    }

    pub fn step_count(&self) -> u64 {
        self.step_count
    }

    pub fn degraded_reason(&self) -> Option<DegradedReason> {
        self.degraded_reason
    }

    #[cfg(test)]
    pub fn writes(&self) -> &[WriteEvidence] {
        &self.writes
    }

    #[cfg(test)]
    pub fn sha3_operations(&self) -> &[Sha3Evidence] {
        &self.sha3_operations
    }

    pub fn into_details(self) -> (Vec<WriteEvidence>, Vec<Sha3Evidence>) {
        (self.writes, self.sha3_operations)
    }

    pub fn observation_keys(&self) -> (Vec<ObservationKey>, bool) {
        if self.degraded_reason.is_some() {
            return (Vec::new(), false);
        }

        let persistent_writes: Vec<_> = self
            .writes
            .iter()
            .filter(|write| write.namespace == StorageNamespace::Persistent)
            .collect();
        if persistent_writes.is_empty() {
            return (Vec::new(), true);
        }

        let mut keys = Vec::with_capacity(self.limits.max_observed_storage.min(1_024));
        let mut set = HashSet::with_capacity(self.limits.max_observed_storage.min(1_024));
        let mut complete = !self.observation_overflow;

        for write in persistent_writes {
            let key = ObservationKey {
                address: write.address,
                slot: U256::from_be_bytes(write.slot.0),
            };
            if set.contains(&key) {
                continue;
            }
            if keys.len() >= self.limits.max_observed_storage {
                complete = false;
                continue;
            }
            set.insert(key);
            keys.push(key);
        }

        for key in &self.sload_keys {
            if set.contains(key) {
                continue;
            }
            if keys.len() >= self.limits.max_observed_storage {
                complete = false;
                continue;
            }
            set.insert(*key);
            keys.push(*key);
        }
        (keys, complete)
    }

    fn degrade(&mut self) {
        if self.degraded_reason.is_some() {
            return;
        }
        self.degraded_reason = Some(DegradedReason::TraceLimit);
        self.writes.clear();
        self.sha3_operations.clear();
        self.sha3_bytes = 0;
        self.pending_write = None;
        self.pending_sha3 = None;
        self.sload_keys.clear();
        self.sload_key_set.clear();
        self.observation_overflow = true;
    }

    fn push_frame(
        &mut self,
        storage_address: Address,
        requested_code_address: Address,
        resolution: CodeResolution,
    ) {
        let id = self.next_frame_id;
        self.next_frame_id = self.next_frame_id.saturating_add(1);
        self.active_frames.push(ActiveFrame {
            id,
            parent_id: self.active_frames.last().map(|frame| frame.id),
            first_write_index: self.writes.len(),
            storage_address,
            requested_code_address,
            code_address: resolution.code_address,
            code_attribution: resolution.attribution,
            code_source: resolution.source,
            code_designator: resolution.designator,
        });
    }

    fn finish_frame(&mut self, failed: bool) {
        let Some(frame) = self.active_frames.pop() else {
            return;
        };
        if !failed || self.degraded_reason.is_some() {
            return;
        }
        for write in &mut self.writes[frame.first_write_index..] {
            if write.frame_id == frame.id {
                write.frame_failed = true;
            }
            write.frame_reverted = true;
            if write.rollback_frame_id.is_none() {
                write.rollback_frame_id = Some(frame.id);
            } else if write.rollback_parent_id.is_none() {
                write.rollback_parent_id = Some(frame.id);
            }
        }
    }

    fn remember_sload(&mut self, address: Address, slot: U256) {
        let key = ObservationKey { address, slot };
        if self.sload_key_set.contains(&key) {
            return;
        }
        if self.sload_keys.len() >= self.limits.max_observed_storage {
            self.observation_overflow = true;
            return;
        }
        self.sload_key_set.insert(key);
        self.sload_keys.push(key);
    }

    fn resolve_code<CTX>(context: &CTX, requested: Address) -> CodeResolution
    where
        CTX: ContextTr<Journal: JournalExt>,
    {
        let delegated = context
            .journal_ref()
            .evm_state()
            .get(&requested)
            .and_then(|account| account.info.code.as_ref())
            .and_then(Bytecode::eip7702_address);
        if let Some(code_address) = delegated {
            CodeResolution {
                code_address: Some(code_address),
                attribution: CodeAttribution::Exact,
                source: CodeSource::Eip7702,
                designator: Some(format!("0xef0100{code_address:x}")),
            }
        } else {
            CodeResolution {
                code_address: Some(requested),
                attribution: CodeAttribution::Exact,
                source: CodeSource::Direct,
                designator: None,
            }
        }
    }

    fn action_failed(interp: &mut Interpreter<EthInterpreter>) -> bool {
        matches!(
            interp.bytecode.action().as_ref(),
            Some(InterpreterAction::Return(result)) if !result.result.is_ok()
        )
    }

    fn word(value: U256) -> B256 {
        B256::new(value.to_be_bytes())
    }
}

#[derive(Clone, Debug)]
struct CodeResolution {
    code_address: Option<Address>,
    attribution: CodeAttribution,
    source: CodeSource,
    designator: Option<String>,
}

impl<CTX> Inspector<CTX, EthInterpreter> for SlotScanInspector
where
    CTX: ContextTr<Journal: JournalExt>,
{
    fn initialize_interp(&mut self, interp: &mut Interpreter<EthInterpreter>, _context: &mut CTX) {
        let Some(frame) = self.active_frames.last_mut() else {
            return;
        };
        if frame.storage_address == Address::ZERO && frame.requested_code_address == Address::ZERO {
            frame.storage_address = interp.input.target_address;
            frame.requested_code_address = interp.input.target_address;
            frame.code_address = Some(interp.input.target_address);
            frame.code_attribution = CodeAttribution::Exact;
            frame.code_source = CodeSource::Direct;
            frame.code_designator = None;
        }
    }

    fn step(&mut self, interp: &mut Interpreter<EthInterpreter>, context: &mut CTX) {
        self.pending_write = None;
        self.pending_sha3 = None;

        if self.degraded_reason.is_some() {
            self.step_count = self.step_count.saturating_add(1);
            return;
        }
        if self.step_count >= self.limits.max_steps {
            self.degrade();
            self.step_count = self.step_count.saturating_add(1);
            return;
        }

        let index = self.step_count;
        self.step_count = self.step_count.saturating_add(1);
        let op = interp.bytecode.opcode();
        let Some(frame) = self.active_frames.last().cloned() else {
            self.degrade();
            return;
        };

        match op {
            opcode::SLOAD => {
                if let Ok(slot) = interp.stack.peek(0) {
                    self.remember_sload(frame.storage_address, slot);
                }
            }
            opcode::SSTORE | opcode::TSTORE => {
                if self.writes.len() >= self.limits.max_writes {
                    self.degrade();
                    return;
                }
                let (Ok(slot), Ok(value)) = (interp.stack.peek(0), interp.stack.peek(1)) else {
                    return;
                };
                let persistent = op == opcode::SSTORE;
                self.pending_write = Some(PendingWrite {
                    address: frame.storage_address,
                    code_address: frame.code_address,
                    code_attribution: frame.code_attribution,
                    code_source: frame.code_source,
                    code_designator: frame.code_designator,
                    pc: interp.bytecode.pc() as u64,
                    slot,
                    value,
                    opcode: if persistent {
                        WriteOpcode::Sstore
                    } else {
                        WriteOpcode::Tstore
                    },
                    namespace: if persistent {
                        StorageNamespace::Persistent
                    } else {
                        StorageNamespace::Transient
                    },
                    depth: self.active_frames.len() as u64,
                    index,
                    frame_id: frame.id,
                    frame_parent_id: frame.parent_id,
                    journal_len: context.journal_ref().journal().len(),
                });
            }
            opcode::KECCAK256 => {
                let (Ok(offset), Ok(size)) = (interp.stack.peek(0), interp.stack.peek(1)) else {
                    return;
                };
                let (Ok(offset), Ok(size)) = (usize::try_from(offset), usize::try_from(size))
                else {
                    return;
                };
                if !(32..=256).contains(&size) {
                    return;
                }
                if self.sha3_operations.len() >= self.limits.max_sha3_operations {
                    self.degrade();
                    return;
                }
                let Some(next_bytes) = self.sha3_bytes.checked_add(size) else {
                    self.degrade();
                    return;
                };
                if next_bytes > self.limits.max_preimage_bytes {
                    self.degrade();
                    return;
                }
                self.pending_sha3 = Some(PendingSha3 {
                    address: frame.storage_address,
                    offset,
                    size,
                    depth: self.active_frames.len() as u64,
                });
            }
            _ => {}
        }
    }

    fn step_end(&mut self, interp: &mut Interpreter<EthInterpreter>, context: &mut CTX) {
        if self.degraded_reason.is_some() {
            self.pending_write = None;
            self.pending_sha3 = None;
            return;
        }

        let failed = Self::action_failed(interp);
        if let Some(pending) = self.pending_write.take() {
            let journal = context.journal_ref().journal();
            let new_entries = journal.get(pending.journal_len..);
            let old_value = new_entries.and_then(|entries| {
                entries.iter().rev().find_map(|entry| match entry {
                    JournalEntry::StorageChanged {
                        address,
                        key,
                        had_value,
                    } if pending.namespace == StorageNamespace::Persistent
                        && *address == pending.address
                        && *key == pending.slot =>
                    {
                        Some(*had_value)
                    }
                    JournalEntry::TransientStorageChange {
                        address,
                        key,
                        had_value,
                    } if pending.namespace == StorageNamespace::Transient
                        && *address == pending.address
                        && *key == pending.slot =>
                    {
                        Some(*had_value)
                    }
                    _ => None,
                })
            });
            let old_value = old_value
                .or_else(|| (new_entries.is_some() && !failed).then_some(pending.value))
                .map(Self::word);
            self.writes.push(WriteEvidence {
                address: pending.address,
                code_address: pending.code_address,
                code_attribution: pending.code_attribution,
                code_source: pending.code_source,
                code_designator: pending.code_designator,
                pc: pending.pc,
                slot: Self::word(pending.slot),
                old_value,
                value: Self::word(pending.value),
                opcode: pending.opcode,
                namespace: pending.namespace,
                depth: pending.depth,
                index: pending.index,
                frame_id: pending.frame_id,
                frame_parent_id: pending.frame_parent_id,
                frame_failed: false,
                frame_reverted: false,
                rollback_frame_id: None,
                rollback_parent_id: None,
            });
        }

        if let Some(pending) = self.pending_sha3.take() {
            if failed {
                return;
            }
            let Some(end) = pending.offset.checked_add(pending.size) else {
                return;
            };
            if end > interp.memory.size() {
                return;
            }
            let preimage =
                Bytes::copy_from_slice(interp.memory.slice(pending.offset..end).as_ref());
            self.sha3_bytes += pending.size;
            self.sha3_operations.push(Sha3Evidence {
                address: pending.address,
                preimage,
                size: pending.size,
                depth: pending.depth,
            });
        }
    }

    fn call(&mut self, context: &mut CTX, inputs: &mut CallInputs) -> Option<CallOutcome> {
        let resolution = Self::resolve_code(context, inputs.bytecode_address);
        self.push_frame(inputs.target_address, inputs.bytecode_address, resolution);
        None
    }

    fn call_end(&mut self, _context: &mut CTX, _inputs: &CallInputs, outcome: &mut CallOutcome) {
        self.finish_frame(!outcome.instruction_result().is_ok());
    }

    fn create(&mut self, _context: &mut CTX, _inputs: &mut CreateInputs) -> Option<CreateOutcome> {
        self.push_frame(
            Address::ZERO,
            Address::ZERO,
            CodeResolution {
                code_address: None,
                attribution: CodeAttribution::Unknown,
                source: CodeSource::Unknown,
                designator: None,
            },
        );
        None
    }

    fn create_end(
        &mut self,
        _context: &mut CTX,
        _inputs: &CreateInputs,
        outcome: &mut CreateOutcome,
    ) {
        self.finish_frame(!outcome.instruction_result().is_ok() || outcome.address.is_none());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use reth_ethereum::evm::revm::revm::{
        context::{Context, TxEnv},
        database::{
            BENCH_CALLER, BENCH_CALLER_BALANCE, BENCH_TARGET, BENCH_TARGET_BALANCE, BenchmarkDB,
            InMemoryDB,
        },
        handler::{MainBuilder, MainContext},
        inspector::InspectEvm,
        primitives::TxKind,
        state::AccountInfo,
    };

    fn limits() -> TraceLimits {
        TraceLimits {
            max_steps: 100,
            max_writes: 10,
            max_sha3_operations: 10,
            max_preimage_bytes: 1_024,
            max_observed_storage: 2,
        }
    }

    fn write(frame_id: u64) -> WriteEvidence {
        WriteEvidence {
            address: Address::repeat_byte(0x11),
            code_address: Some(Address::repeat_byte(0x22)),
            code_attribution: CodeAttribution::Exact,
            code_source: CodeSource::Direct,
            code_designator: None,
            pc: 1,
            slot: B256::ZERO,
            old_value: Some(B256::ZERO),
            value: B256::repeat_byte(1),
            opcode: WriteOpcode::Sstore,
            namespace: StorageNamespace::Persistent,
            depth: 1,
            index: 1,
            frame_id,
            frame_parent_id: None,
            frame_failed: false,
            frame_reverted: false,
            rollback_frame_id: None,
            rollback_parent_id: None,
        }
    }

    fn execute(code: Vec<u8>, limits: TraceLimits) -> (bool, SlotScanInspector) {
        let context =
            Context::mainnet().with_db(BenchmarkDB::new_bytecode(Bytecode::new_raw(code.into())));
        let mut evm = context.build_mainnet_with_inspector(SlotScanInspector::new(limits));
        let result = evm
            .inspect_one_tx(
                TxEnv::builder()
                    .caller(BENCH_CALLER)
                    .kind(TxKind::Call(BENCH_TARGET))
                    .gas_limit(1_000_000)
                    .build()
                    .unwrap(),
            )
            .unwrap();
        (result.is_success(), evm.inspector)
    }

    fn account(code: Bytecode, balance: U256) -> AccountInfo {
        AccountInfo {
            balance,
            nonce: 1,
            code_hash: code.hash_slow(),
            code: Some(code),
            ..Default::default()
        }
    }

    fn execute_accounts(
        target_code: Vec<u8>,
        extra_accounts: impl IntoIterator<Item = (Address, Bytecode)>,
        limits: TraceLimits,
    ) -> (bool, SlotScanInspector) {
        let mut db = InMemoryDB::default();
        db.insert_account_info(
            BENCH_CALLER,
            AccountInfo {
                balance: BENCH_CALLER_BALANCE,
                ..Default::default()
            },
        );
        db.insert_account_info(
            BENCH_TARGET,
            account(Bytecode::new_raw(target_code.into()), BENCH_TARGET_BALANCE),
        );
        for (address, code) in extra_accounts {
            db.insert_account_info(address, account(code, U256::ZERO));
        }

        let context = Context::mainnet().with_db(db);
        let mut evm = context.build_mainnet_with_inspector(SlotScanInspector::new(limits));
        let result = evm
            .inspect_one_tx(
                TxEnv::builder()
                    .caller(BENCH_CALLER)
                    .kind(TxKind::Call(BENCH_TARGET))
                    .gas_limit(1_000_000)
                    .build()
                    .unwrap(),
            )
            .unwrap();
        (result.is_success(), evm.inspector)
    }

    fn child_call_code(op: u8, target: Address) -> Vec<u8> {
        let mut code = vec![
            opcode::PUSH1,
            0,
            opcode::PUSH1,
            0,
            opcode::PUSH1,
            0,
            opcode::PUSH1,
            0,
        ];
        if op == opcode::CALL || op == opcode::CALLCODE {
            code.extend([opcode::PUSH1, 0]);
        }
        code.push(opcode::PUSH20);
        code.extend_from_slice(target.as_slice());
        code.extend([opcode::PUSH2, 0xff, 0xff, op]);
        code
    }

    #[test]
    fn nested_failures_preserve_nearest_and_parent_rollback_frames() {
        let mut inspector = SlotScanInspector::new(limits());
        inspector.push_frame(
            Address::repeat_byte(1),
            Address::repeat_byte(1),
            CodeResolution {
                code_address: Some(Address::repeat_byte(1)),
                attribution: CodeAttribution::Exact,
                source: CodeSource::Direct,
                designator: None,
            },
        );
        inspector.push_frame(
            Address::repeat_byte(2),
            Address::repeat_byte(2),
            CodeResolution {
                code_address: Some(Address::repeat_byte(2)),
                attribution: CodeAttribution::Exact,
                source: CodeSource::Direct,
                designator: None,
            },
        );
        inspector.writes.push(write(1));

        inspector.finish_frame(true);
        inspector.finish_frame(true);

        let captured = &inspector.writes[0];
        assert!(captured.frame_failed);
        assert!(captured.frame_reverted);
        assert_eq!(captured.rollback_frame_id, Some(1));
        assert_eq!(captured.rollback_parent_id, Some(0));
    }

    #[test]
    fn persistent_write_keys_take_priority_over_sload_observations() {
        let mut inspector = SlotScanInspector::new(limits());
        inspector.remember_sload(Address::repeat_byte(1), U256::from(1));
        inspector.remember_sload(Address::repeat_byte(1), U256::from(2));
        inspector.writes.push(WriteEvidence {
            address: Address::repeat_byte(3),
            slot: B256::repeat_byte(3),
            ..write(0)
        });

        let (keys, complete) = inspector.observation_keys();

        assert!(!complete);
        assert_eq!(keys.len(), 2);
        assert_eq!(keys[0].address, Address::repeat_byte(3));
        assert_eq!(keys[1].slot, U256::from(1));
    }

    #[test]
    fn degradation_clears_partial_details_without_stopping_step_accounting() {
        let mut inspector = SlotScanInspector::new(limits());
        inspector.writes.push(write(0));
        inspector.sha3_operations.push(Sha3Evidence {
            address: Address::repeat_byte(1),
            preimage: Bytes::from(vec![0; 32]),
            size: 32,
            depth: 1,
        });

        inspector.degrade();

        assert_eq!(
            inspector.degraded_reason(),
            Some(DegradedReason::TraceLimit)
        );
        assert!(inspector.writes().is_empty());
        assert!(inspector.sha3_operations().is_empty());
        assert_eq!(inspector.observation_keys(), (Vec::new(), false));
    }

    #[test]
    fn read_only_execution_has_no_observation_payload() {
        let mut inspector = SlotScanInspector::new(limits());
        inspector.remember_sload(Address::repeat_byte(1), U256::from(1));
        assert_eq!(inspector.observation_keys(), (Vec::new(), true));

        let (succeeded, inspector) = execute(
            vec![opcode::PUSH1, 0, opcode::SLOAD, opcode::POP, opcode::STOP],
            limits(),
        );
        assert!(succeeded);
        assert_eq!(inspector.observation_keys(), (Vec::new(), true));
    }

    #[test]
    fn execution_preserves_repeated_noop_and_restored_writes_with_old_values() {
        let code = vec![
            opcode::PUSH1,
            1,
            opcode::PUSH1,
            0,
            opcode::SSTORE,
            opcode::PUSH1,
            1,
            opcode::PUSH1,
            0,
            opcode::SSTORE,
            opcode::PUSH1,
            2,
            opcode::PUSH1,
            0,
            opcode::SSTORE,
            opcode::PUSH1,
            0,
            opcode::PUSH1,
            0,
            opcode::SSTORE,
            opcode::STOP,
        ];

        let (succeeded, inspector) = execute(code, limits());

        assert!(succeeded);
        let writes = inspector.writes();
        assert_eq!(writes.len(), 4);
        assert_eq!(
            writes.iter().map(|write| write.index).collect::<Vec<_>>(),
            [2, 5, 8, 11]
        );
        assert_eq!(
            writes
                .iter()
                .map(|write| write.old_value.unwrap())
                .collect::<Vec<_>>(),
            [
                B256::ZERO,
                B256::with_last_byte(1),
                B256::with_last_byte(1),
                B256::with_last_byte(2),
            ]
        );
        assert_eq!(
            writes.iter().map(|write| write.value).collect::<Vec<_>>(),
            [
                B256::with_last_byte(1),
                B256::with_last_byte(1),
                B256::with_last_byte(2),
                B256::ZERO,
            ]
        );
    }

    #[test]
    fn execution_records_transient_writes_and_immediate_old_values() {
        let code = vec![
            opcode::PUSH1,
            7,
            opcode::PUSH1,
            3,
            opcode::TSTORE,
            opcode::PUSH1,
            9,
            opcode::PUSH1,
            3,
            opcode::TSTORE,
            opcode::STOP,
        ];

        let (succeeded, inspector) = execute(code, limits());

        assert!(succeeded);
        let writes = inspector.writes();
        assert_eq!(writes.len(), 2);
        assert!(
            writes
                .iter()
                .all(|write| write.namespace == StorageNamespace::Transient)
        );
        assert_eq!(writes[0].old_value, Some(B256::ZERO));
        assert_eq!(writes[1].old_value, Some(B256::with_last_byte(7)));
    }

    #[test]
    fn root_revert_keeps_and_annotates_attempted_write() {
        let code = vec![
            opcode::PUSH1,
            1,
            opcode::PUSH1,
            0,
            opcode::SSTORE,
            opcode::PUSH1,
            0,
            opcode::PUSH1,
            0,
            opcode::REVERT,
        ];

        let (succeeded, inspector) = execute(code, limits());

        assert!(!succeeded);
        let write = &inspector.writes()[0];
        assert!(write.frame_failed);
        assert!(write.frame_reverted);
        assert_eq!(write.rollback_frame_id, Some(0));
        assert_eq!(write.rollback_parent_id, None);
    }

    #[test]
    fn sha3_limit_degrades_without_stopping_execution() {
        let code = vec![
            opcode::PUSH1,
            0x2a,
            opcode::PUSH1,
            0,
            opcode::MSTORE,
            opcode::PUSH1,
            32,
            opcode::PUSH1,
            0,
            opcode::KECCAK256,
            opcode::POP,
            opcode::PUSH1,
            32,
            opcode::PUSH1,
            0,
            opcode::KECCAK256,
            opcode::POP,
            opcode::STOP,
        ];
        let (succeeded, captured) = execute(code.clone(), limits());
        assert!(succeeded);
        assert_eq!(captured.sha3_operations().len(), 2);
        assert_eq!(captured.sha3_operations()[0].size, 32);
        assert_eq!(captured.sha3_operations()[0].preimage.len(), 32);
        assert_eq!(captured.sha3_operations()[0].preimage[31], 0x2a);

        for bounded in [
            TraceLimits {
                max_sha3_operations: 1,
                ..limits()
            },
            TraceLimits {
                max_preimage_bytes: 31,
                ..limits()
            },
        ] {
            let (succeeded, inspector) = execute(code.clone(), bounded);
            assert!(succeeded);
            assert_eq!(
                inspector.degraded_reason(),
                Some(DegradedReason::TraceLimit)
            );
            assert!(inspector.sha3_operations().is_empty());
            assert!(inspector.writes().is_empty());
            assert_eq!(inspector.step_count(), 12);
        }
    }

    #[test]
    fn write_and_step_limits_degrade_without_changing_execution_outcome() {
        let code = vec![
            opcode::PUSH1,
            1,
            opcode::PUSH1,
            0,
            opcode::SSTORE,
            opcode::PUSH1,
            2,
            opcode::PUSH1,
            1,
            opcode::SSTORE,
            opcode::STOP,
        ];
        for bounded in [
            TraceLimits {
                max_writes: 1,
                ..limits()
            },
            TraceLimits {
                max_steps: 4,
                ..limits()
            },
        ] {
            let (succeeded, inspector) = execute(code.clone(), bounded);
            assert!(succeeded);
            assert_eq!(
                inspector.degraded_reason(),
                Some(DegradedReason::TraceLimit)
            );
            assert!(inspector.writes().is_empty());
            assert!(inspector.step_count() > bounded.max_steps || bounded.max_writes == 1);
        }
    }

    #[test]
    fn delegatecall_and_callcode_keep_the_parent_storage_owner() {
        let child = Address::with_last_byte(0x42);
        let child_code = Bytecode::new_raw(
            vec![
                opcode::PUSH1,
                1,
                opcode::PUSH1,
                0,
                opcode::SSTORE,
                opcode::STOP,
            ]
            .into(),
        );

        for call_opcode in [opcode::DELEGATECALL, opcode::CALLCODE] {
            let mut root_code = child_call_code(call_opcode, child);
            root_code.extend([opcode::POP, opcode::STOP]);
            let (succeeded, inspector) =
                execute_accounts(root_code, [(child, child_code.clone())], limits());

            assert!(succeeded);
            let write = &inspector.writes()[0];
            assert_eq!(write.address, BENCH_TARGET);
            assert_eq!(write.code_address, Some(child));
            assert_eq!(write.code_attribution, CodeAttribution::Exact);
            assert_eq!(write.code_source, CodeSource::Direct);
            assert_eq!(write.depth, 2);
            assert_eq!(write.frame_parent_id, Some(0));
        }
    }

    #[test]
    fn caught_child_revert_keeps_child_write_and_later_parent_write() {
        let child = Address::with_last_byte(0x43);
        let child_code = Bytecode::new_raw(
            vec![
                opcode::PUSH1,
                1,
                opcode::PUSH1,
                0,
                opcode::SSTORE,
                opcode::PUSH1,
                0,
                opcode::PUSH1,
                0,
                opcode::REVERT,
            ]
            .into(),
        );
        let mut root_code = child_call_code(opcode::CALL, child);
        root_code.extend([
            opcode::POP,
            opcode::PUSH1,
            2,
            opcode::PUSH1,
            1,
            opcode::SSTORE,
            opcode::STOP,
        ]);

        let (succeeded, inspector) = execute_accounts(root_code, [(child, child_code)], limits());

        assert!(succeeded);
        let writes = inspector.writes();
        assert_eq!(writes.len(), 2);
        assert_eq!(writes[0].address, child);
        assert!(writes[0].frame_failed);
        assert!(writes[0].frame_reverted);
        assert_eq!(writes[0].rollback_frame_id, Some(1));
        assert_eq!(writes[1].address, BENCH_TARGET);
        assert!(!writes[1].frame_failed);
        assert!(!writes[1].frame_reverted);
    }

    #[test]
    fn faulted_write_attempt_keeps_unknown_old_value_instead_of_guessing() {
        let child = Address::with_last_byte(0x45);
        let child_code = Bytecode::new_raw(
            vec![
                opcode::PUSH1,
                1,
                opcode::PUSH1,
                0,
                opcode::SSTORE,
                opcode::STOP,
            ]
            .into(),
        );
        let mut root_code = child_call_code(opcode::STATICCALL, child);
        root_code.extend([opcode::POP, opcode::STOP]);

        let (succeeded, inspector) = execute_accounts(root_code, [(child, child_code)], limits());

        assert!(succeeded);
        let write = &inspector.writes()[0];
        assert_eq!(write.old_value, None);
        assert!(write.frame_failed);
        assert!(write.frame_reverted);
    }

    #[test]
    fn successful_and_failed_creation_keep_constructor_writes() {
        for failed in [false, true] {
            for create2 in [false, true] {
                let mut init_code = vec![
                    opcode::PUSH1,
                    1,
                    opcode::PUSH1,
                    0,
                    opcode::SSTORE,
                    opcode::PUSH1,
                    0,
                    opcode::PUSH1,
                    0,
                ];
                init_code.push(if failed {
                    opcode::REVERT
                } else {
                    opcode::RETURN
                });
                let init_offset = if create2 { 18 } else { 16 };
                let mut root_code = Vec::new();
                if create2 {
                    root_code.extend([opcode::PUSH1, 7]);
                }
                root_code.extend([
                    opcode::PUSH1,
                    init_code.len() as u8,
                    opcode::PUSH1,
                    init_offset,
                    opcode::PUSH1,
                    0,
                    opcode::CODECOPY,
                    opcode::PUSH1,
                    init_code.len() as u8,
                    opcode::PUSH1,
                    0,
                    opcode::PUSH1,
                    0,
                    if create2 {
                        opcode::CREATE2
                    } else {
                        opcode::CREATE
                    },
                    opcode::POP,
                    opcode::STOP,
                ]);
                root_code.extend(init_code);

                let (succeeded, inspector) = execute(root_code, limits());

                assert!(succeeded);
                let write = &inspector.writes()[0];
                assert_ne!(write.address, Address::ZERO);
                assert_eq!(write.code_address, Some(write.address));
                assert_eq!(write.code_source, CodeSource::Direct);
                assert_eq!(write.frame_failed, failed);
                assert_eq!(write.frame_reverted, failed);
            }
        }
    }

    #[test]
    fn eip7702_designation_attributes_code_without_changing_storage_owner() {
        let delegated = Address::with_last_byte(0x44);
        let delegated_code = Bytecode::new_raw(
            vec![
                opcode::PUSH1,
                1,
                opcode::PUSH1,
                0,
                opcode::SSTORE,
                opcode::STOP,
            ]
            .into(),
        );
        let designated_code = Bytecode::new_eip7702(delegated);

        let (succeeded, inspector) = execute_accounts(
            Vec::new(),
            [(BENCH_TARGET, designated_code), (delegated, delegated_code)],
            limits(),
        );

        assert!(succeeded);
        let write = &inspector.writes()[0];
        assert_eq!(write.address, BENCH_TARGET);
        assert_eq!(write.code_address, Some(delegated));
        assert_eq!(write.code_source, CodeSource::Eip7702);
        assert_eq!(
            write.code_designator.as_deref(),
            Some(format!("0xef0100{delegated:x}").as_str())
        );
    }
}
