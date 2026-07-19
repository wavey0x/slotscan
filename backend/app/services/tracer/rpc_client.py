"""RPC client for trace operations."""

from dataclasses import dataclass
import logging
import re
from typing import Any

from web3 import Web3

from app.config import Settings
from app.models.errors import RPCError, TraceNotAvailableError, TransactionNotFoundError
from app.services.web3_provider import Web3Provider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompactTraceEvidence:
    writes: list[dict]
    sha3_operations: list[dict]
    observed_storage: dict[str, dict[str, str | None]]
    observed_storage_complete: bool
    evm_step_count: int
    degraded_reason: str | None = None


class TraceRPCClient:
    """Handles RPC calls for transaction tracing."""

    def __init__(
        self,
        web3_provider: Web3Provider,
        settings: Settings | None = None,
    ):
        self.web3_provider = web3_provider
        self.max_writes = settings.max_sstore_ops if settings else 10_000
        self.max_steps = settings.max_trace_steps if settings else 5_000_000
        self.max_sha3_ops = settings.max_trace_sha3_ops if settings else 20_000
        self.max_preimage_bytes = (
            settings.max_trace_preimage_bytes if settings else 5 * 1024 * 1024
        )
        self.max_prestate_accounts = (
            settings.max_prestate_accounts if settings else 10_000
        )
        self.max_prestate_storage_entries = (
            settings.max_prestate_storage_entries if settings else 100_000
        )
        self.max_observed_storage = self.max_prestate_storage_entries

    async def get_receipt(self, chain_id: int, tx_hash: str) -> dict:
        """Fetch transaction receipt with error handling."""
        try:
            receipt = await self.web3_provider.get_transaction_receipt(chain_id, tx_hash)
        except Exception as e:
            error_msg = str(e).lower()
            if "not found" in error_msg or "transaction receipt" in error_msg:
                raise TransactionNotFoundError(tx_hash)
            raise RPCError("eth_getTransactionReceipt", str(e))

        if receipt is None:
            raise TransactionNotFoundError(tx_hash)
        return receipt

    async def execute_prestate_diff(self, chain_id: int, tx_hash: str) -> dict:
        """Execute debug_traceTransaction with the diff-mode prestate tracer."""
        tracer_config = {
            "tracer": "prestateTracer",
            "tracerConfig": {"diffMode": True},
        }

        try:
            result = await self.web3_provider.make_request(
                chain_id, "debug_traceTransaction", [tx_hash, tracer_config]
            )
        except Exception as e:
            error_msg = str(e).lower()
            if "method not found" in error_msg or "not supported" in error_msg:
                raise TraceNotAvailableError(
                    "Node does not support debug_traceTransaction"
                )
            raise RPCError("debug_traceTransaction", str(e))

        if "error" in result:
            error = result["error"]
            if isinstance(error, dict):
                error_msg = error.get("message", str(error))
            else:
                error_msg = str(error)
            if any(
                marker in error_msg.lower()
                for marker in (
                    "method not found",
                    "not supported",
                    "unknown tracer",
                    "debug api is disabled",
                )
            ):
                raise TraceNotAvailableError(error_msg)
            raise RPCError("debug_traceTransaction", error_msg)

        trace = result.get("result", {})
        self._validate_prestate_size(trace)
        return trace

    async def execute_compact_trace(
        self,
        chain_id: int,
        tx_hash: str,
    ) -> CompactTraceEvidence:
        """Extract compact write and SHA3 evidence with the Reth JS tracer.

        Internal frame identity comes exclusively from ``enter``/``exit``
        hooks. Malformed or partial evidence fails closed; raw struct-log
        reconstruction is deliberately unsupported.

        Returns one bounded evidence object with an optional degradation reason.
        """
        try:
            compact = await self._execute_compact_storage_trace(chain_id, tx_hash)
        except TraceNotAvailableError as exc:
            logger.warning(
                "Compact storage trace reached a safety limit for %s: %s",
                tx_hash,
                exc.reason,
            )
            return CompactTraceEvidence(
                writes=[],
                sha3_operations=[],
                observed_storage={},
                observed_storage_complete=False,
                evm_step_count=0,
                degraded_reason="trace_limit",
            )
        if compact is not None:
            return compact
        logger.warning(
            "Compact storage tracer unavailable for %s; raw structLogs are disabled",
            tx_hash,
        )
        return CompactTraceEvidence(
            writes=[],
            sha3_operations=[],
            observed_storage={},
            observed_storage_complete=False,
            evm_step_count=0,
            degraded_reason="tracer_unavailable",
        )

    async def _execute_compact_storage_trace(
        self,
        chain_id: int,
        tx_hash: str,
    ) -> CompactTraceEvidence | None:
        """Run a compact node-side forensic tracer before raw struct logs.

        Full opcode traces can exceed provider response limits. This tracer
        returns only storage writes, SHA3 evidence, and bounded transaction-start
        storage observations while retaining code attribution and frame outcomes.
        """
        tracer = self._compact_storage_tracer_source()
        try:
            response = await self.web3_provider.make_request(
                chain_id,
                "debug_traceTransaction",
                [tx_hash, {"tracer": tracer}],
            )
        except Exception as exc:
            if "slotscan trace limit exceeded" in str(exc).lower():
                raise TraceNotAvailableError("Trace exceeds configured limits")
            logger.info("Compact storage tracer unavailable: %s", exc)
            return None

        if "error" in response:
            if "slotscan trace limit exceeded" in str(response["error"]).lower():
                raise TraceNotAvailableError("Trace exceeds configured limits")
            logger.info(
                "Compact storage tracer rejected: %s",
                response["error"],
            )
            return None
        result = response.get("result")
        try:
            return self._decode_compact_trace_result(result)
        except TraceNotAvailableError:
            raise
        except (TypeError, ValueError) as exc:
            logger.info("Compact storage tracer returned malformed evidence: %s", exc)
            return None

    def _compact_storage_tracer_source(self) -> str:
        tracer = r"""
        {
          writes: [], sha3s: [], frames: {}, frameStack: [],
          observedKeys: [], observedKeySet: {}, observedOverflow: false,
          pendingCompletions: {}, nextFrameId: 1,
          steps: 0, hookEnters: 0, hookExits: 0,
          lastOp: null, lastDepth: null, sha3Bytes: 0, fatal: null,
          isCall: function(type) {
            return type === 'CALL' || type === 'STATICCALL' ||
              type === 'DELEGATECALL' || type === 'CALLCODE';
          },
          isCreate: function(type) {
            return type === 'CREATE' || type === 'CREATE2';
          },
          wordHex: function(word) {
            var hex = word.toString(16);
            while (hex.length < 64) hex = '0' + hex;
            return '0x' + hex;
          },
          wordAddress: function(word) {
            var hex = word.toString(16);
            while (hex.length < 40) hex = '0' + hex;
            return '0x' + hex.slice(-40).toLowerCase();
          },
          hexBytes: function(hex, size) {
            var clean = hex.slice(0, 2) === '0x' ? hex.slice(2) : hex;
            if (clean.length !== size * 2) {
              throw new Error('slotscan state key has invalid width');
            }
            var output = new Uint8Array(size);
            for (var i = 0; i < size; i++) {
              output[i] = (
                parseInt(clean.slice(i * 2, i * 2 + 2), 16) | 0
              );
            }
            return output;
          },
          stateWord: function(value) {
            var hex = toHex(value).toLowerCase();
            var clean = hex.slice(0, 2) === '0x' ? hex.slice(2) : hex;
            while (clean.length < 64) clean = '0' + clean;
            if (clean.length !== 64) {
              throw new Error('slotscan state value has invalid width');
            }
            return '0x' + clean;
          },
          rememberSload: function(address, slot) {
            var key = address + ':' + slot;
            if (this.observedKeySet[key]) return;
            if (this.observedKeys.length >= __MAX_OBSERVED_STORAGE__) {
              this.observedOverflow = true;
              return;
            }
            this.observedKeySet[key] = true;
            this.observedKeys.push({address: address, slot: slot});
          },
          resolveCode: function(requested, db) {
            var requestedHex = (
              typeof requested === 'string' ? requested : toHex(requested)
            ).toLowerCase();
            var rawCode = toHex(db.getCode(requestedHex)).toLowerCase();
            if (rawCode.slice(0, 8) === '0xef0100') {
              if (rawCode.length === 48) {
                return {
                  code: '0x' + rawCode.slice(8),
                  attribution: 'exact',
                  source: 'eip7702',
                  designator: rawCode
                };
              }
              return {
                code: null,
                attribution: 'unknown',
                source: 'unknown',
                designator: null
              };
            }
            return {
              code: requestedHex,
              attribution: 'exact',
              source: 'direct',
              designator: null
            };
          },
          applyCodeResolution: function(frame, resolution) {
            frame.code_address = resolution.code;
            frame.code_attribution = resolution.attribution;
            frame.code_source = resolution.source;
            frame.code_designator = resolution.designator;
          },
          currentFrame: function() {
            if (this.frameStack.length === 0) {
              throw new Error('slotscan frame stack is empty');
            }
            return this.frames[this.frameStack[this.frameStack.length - 1]];
          },
          ensureRoot: function(log, db) {
            if (this.frameStack.length !== 0) return;
            var requested = toHex(log.contract.getAddress()).toLowerCase();
            var frame = {
              id: 0,
              parent_id: null,
              type: 'ROOT',
              depth: log.getDepth(),
              storage_address: requested,
              requested_code_address: requested,
              code_address: null,
              code_attribution: 'unknown',
              code_source: 'unknown',
              code_designator: null,
              target_confirmed: true,
              faulted: false,
              exit_error: null,
              outcome: 'open',
              completion_validated: true,
              completion_word: null,
              has_writes: false
            };
            this.applyCodeResolution(frame, this.resolveCode(requested, db));
            this.frames[0] = frame;
            this.frameStack.push(0);
          },
          confirmCurrentFrame: function(log, db) {
            var frame = this.currentFrame();
            if (frame.target_confirmed) return;
            var actualStorage = toHex(log.contract.getAddress()).toLowerCase();
            if (actualStorage !== frame.storage_address ||
                log.getDepth() !== frame.depth) {
              throw new Error('slotscan hook/step context mismatch');
            }
            this.applyCodeResolution(
              frame,
              this.resolveCode(frame.requested_code_address, db)
            );
            frame.target_confirmed = true;
          },
          consumeCompletion: function(log) {
            var parent = this.currentFrame();
            var completion = this.pendingCompletions[parent.id];
            if (!completion) return;
            if (log.stack.length() < 1) {
              throw new Error('slotscan child return word is missing');
            }
            var child = this.frames[completion.frame_id];
            var word = this.wordHex(log.stack.peek(0));
            var failed = false;
            if (this.isCall(child.type)) {
              if (word !== '0x' + '0'.repeat(64) &&
                  word !== '0x' + '0'.repeat(63) + '1') {
                throw new Error('slotscan call return word is malformed');
              }
              failed = word === '0x' + '0'.repeat(64);
              var exitFailed = child.faulted || child.exit_error !== null;
              if (failed !== exitFailed) {
                throw new Error('slotscan call completion contradicts exit');
              }
            } else if (this.isCreate(child.type)) {
              failed = word === '0x' + '0'.repeat(64);
              if (!failed &&
                  this.wordAddress(log.stack.peek(0)) !==
                    child.requested_code_address) {
                throw new Error('slotscan creation return address mismatch');
              }
              if (!failed && (child.faulted || child.exit_error !== null)) {
                throw new Error('slotscan creation success contradicts exit');
              }
            } else {
              throw new Error('slotscan completion has unsupported frame type');
            }
            child.outcome = failed ? 'failed' : 'succeeded';
            child.completion_validated = true;
            child.completion_word = word;
            delete this.pendingCompletions[parent.id];
          },
          reachLimit: function(marker) {
            this.fatal = marker;
            throw new Error('slotscan trace limit exceeded: ' + marker);
          },
          rethrow: function(error) {
            if (this.fatal === null) this.fatal = 'tracer:exception';
            throw error;
          },
          onStep: function(log, db) {
            if (this.steps >= __MAX_STEPS__) this.reachLimit('limit:steps');
            this.ensureRoot(log, db);
            this.consumeCompletion(log);
            this.confirmCurrentFrame(log, db);
            var frame = this.currentFrame();
            var op = log.op.toString();
            this.lastOp = op;
            this.lastDepth = log.getDepth();
            if (op === 'SLOAD') {
              this.rememberSload(
                frame.storage_address,
                this.wordHex(log.stack.peek(0))
              );
            } else if (op === 'SSTORE' || op === 'TSTORE') {
              if (this.writes.length >= __MAX_WRITES__) {
                this.reachLimit('limit:writes');
              }
              frame.has_writes = true;
              this.writes.push({
                pc: log.getPC(),
                slot: this.wordHex(log.stack.peek(0)),
                value: this.wordHex(log.stack.peek(1)),
                old_value: null,
                opcode: op,
                namespace: op === 'SSTORE' ? 'persistent' : 'transient',
                depth: log.getDepth(),
                index: this.steps,
                frame_id: frame.id
              });
            } else if (op === 'SHA3' || op === 'KECCAK256') {
              var offset = parseInt(log.stack.peek(0).toString());
              var size = parseInt(log.stack.peek(1).toString());
              if (size >= 32 && size <= 256) {
                if (this.sha3s.length >= __MAX_SHA3S__) {
                  this.reachLimit('limit:sha3');
                }
                if (this.sha3Bytes + size > __MAX_SHA3_BYTES__) {
                  this.reachLimit('limit:preimage_bytes');
                }
                this.sha3s.push({
                  address: frame.storage_address,
                  preimage: toHex(log.memory.slice(offset, offset + size)),
                  size: size,
                  depth: log.getDepth()
                });
                this.sha3Bytes += size;
              }
            }
            this.steps += 1;
          },
          onFault: function(log, db) {
            if (this.steps >= __MAX_STEPS__) this.reachLimit('limit:steps');
            this.ensureRoot(log, db);
            this.consumeCompletion(log);
            this.confirmCurrentFrame(log, db);
            var frame = this.currentFrame();
            frame.faulted = true;
            this.lastOp = log.op.toString();
            this.lastDepth = log.getDepth();
            this.steps += 1;
          },
          onEnter: function(call) {
            var parent = this.currentFrame();
            var type = call.getType().toString();
            if (!this.isCall(type) && !this.isCreate(type)) {
              throw new Error('slotscan unsupported hook frame type');
            }
            var target = toHex(call.getTo()).toLowerCase();
            var storage = (
              type === 'DELEGATECALL' || type === 'CALLCODE'
            ) ? parent.storage_address : target;
            var id = this.nextFrameId++;
            this.frames[id] = {
              id: id,
              parent_id: parent.id,
              type: type,
              depth: parent.depth + 1,
              storage_address: storage,
              requested_code_address: target,
              code_address: null,
              code_attribution: 'unknown',
              code_source: 'unknown',
              code_designator: null,
              target_confirmed: false,
              faulted: false,
              exit_error: null,
              outcome: 'open',
              completion_validated: false,
              completion_word: null,
              has_writes: false
            };
            this.frameStack.push(id);
            this.hookEnters += 1;
          },
          onExit: function(result) {
            if (this.frameStack.length <= 1) {
              throw new Error('slotscan unmatched exit hook');
            }
            var child = this.currentFrame();
            var rawError = result.getError();
            child.exit_error = (
              typeof rawError === 'undefined' ? null : String(rawError)
            );
            child.outcome = (
              child.faulted || child.exit_error !== null
            ) ? 'failed' : 'succeeded';
            this.frameStack.pop();
            this.hookExits += 1;
            if (!child.has_writes) return;
            var parent = this.currentFrame();
            parent.has_writes = true;
            if (this.pendingCompletions[parent.id]) {
              throw new Error('slotscan parent has two pending completions');
            }
            this.pendingCompletions[parent.id] = {frame_id: child.id};
          },
          step: function(log, db) {
            try {
              this.onStep(log, db);
            } catch (error) {
              this.rethrow(error);
            }
          },
          fault: function(log, db) {
            try {
              this.onFault(log, db);
            } catch (error) {
              this.rethrow(error);
            }
          },
          enter: function(call) {
            try {
              this.onEnter(call);
            } catch (error) {
              this.rethrow(error);
            }
          },
          exit: function(result) {
            try {
              this.onExit(result);
            } catch (error) {
              this.rethrow(error);
            }
          },
          fatalResult: function() {
            return {
              fatal: this.fatal,
              stepCount: this.steps,
              hookEnters: this.hookEnters,
              hookExits: this.hookExits
            };
          },
          result: function(ctx, db) {
            if (this.fatal !== null) return this.fatalResult();
            var executable = this.frames[0] !== undefined;
            if (!executable) {
              if (this.steps !== 0 || this.hookEnters !== 0 ||
                  this.hookExits !== 0 || this.writes.length !== 0 ||
                  this.sha3s.length !== 0 || this.frameStack.length !== 0) {
                this.fatal = 'tracer:exception';
                return this.fatalResult();
              }
              return {
                fatal: null,
                executable: false,
                stepCount: 0,
                hookEnters: 0,
                hookExits: 0,
                frameStack: [],
                writes: [],
                sha3s: [],
                frames: [],
                observedStorage: {},
                observedStorageComplete: true,
                lastOp: null,
                lastDepth: null
              };
            }
            if (this.hookEnters !== this.hookExits ||
                this.frameStack.length !== 1 ||
                this.frameStack[0] !== 0) {
              this.fatal = 'tracer:exception';
              return this.fatalResult();
            }
            for (var pendingParent in this.pendingCompletions) {
              this.fatal = 'tracer:exception';
              return this.fatalResult();
            }
            var root = this.frames[0];
            root.exit_error = ctx.error ? String(ctx.error) : null;
            root.outcome = (
              root.faulted || root.exit_error !== null
            ) ? 'failed' : 'succeeded';
            var needed = {};
            for (var i = 0; i < this.writes.length; i++) {
              var current = this.writes[i].frame_id;
              while (current !== null && current !== undefined) {
                var evidenceFrame = this.frames[current];
                if (!evidenceFrame) {
                  this.fatal = 'tracer:exception';
                  return this.fatalResult();
                }
                needed[current] = true;
                current = evidenceFrame.parent_id;
              }
            }
            var outputFrames = [];
            for (var frameId in needed) {
              var frame = this.frames[frameId];
              if (!frame.target_confirmed || frame.outcome === 'open' ||
                  (frame.id !== 0 && !frame.completion_validated)) {
                this.fatal = 'tracer:exception';
                return this.fatalResult();
              }
              outputFrames.push({
                id: frame.id,
                parent_id: frame.parent_id,
                type: frame.type,
                depth: frame.depth,
                storage_address: frame.storage_address,
                requested_code_address: frame.requested_code_address,
                code_address: frame.code_address,
                code_attribution: frame.code_attribution,
                code_source: frame.code_source,
                code_designator: frame.code_designator,
                target_confirmed: frame.target_confirmed,
                faulted: frame.faulted,
                exit_error: frame.exit_error,
                outcome: frame.outcome,
                completion_validated: frame.completion_validated,
                completion_word: frame.completion_word
              });
            }
            var observationKeys = [];
            var observationSet = {};
            var observedStorage = {};
            var observedStorageComplete = true;
            var hasPersistentWrites = false;
            var addObservation = function(address, slot) {
              var key = address + ':' + slot;
              if (observationSet[key]) return;
              if (observationKeys.length >= __MAX_OBSERVED_STORAGE__) {
                observedStorageComplete = false;
                return;
              }
              observationSet[key] = true;
              observationKeys.push({address: address, slot: slot});
            };
            for (var writeIndex = 0;
                 writeIndex < this.writes.length;
                 writeIndex++) {
              var write = this.writes[writeIndex];
              if (write.namespace !== 'persistent') continue;
              hasPersistentWrites = true;
              addObservation(
                this.frames[write.frame_id].storage_address,
                write.slot
              );
            }
            if (hasPersistentWrites) {
              if (this.observedOverflow) observedStorageComplete = false;
              for (var observedIndex = 0;
                   observedIndex < this.observedKeys.length;
                   observedIndex++) {
                var observedKey = this.observedKeys[observedIndex];
                addObservation(observedKey.address, observedKey.slot);
              }
              for (var stateIndex = 0;
                   stateIndex < observationKeys.length;
                   stateIndex++) {
                var stateKey = observationKeys[stateIndex];
                if (!observedStorage[stateKey.address]) {
                  observedStorage[stateKey.address] = {};
                }
                try {
                  observedStorage[stateKey.address][stateKey.slot] =
                    this.stateWord(
                      db.getState(
                        this.hexBytes(stateKey.address, 20),
                        this.hexBytes(stateKey.slot, 32)
                      )
                    );
                } catch (error) {
                  observedStorage[stateKey.address][stateKey.slot] = null;
                  observedStorageComplete = false;
                }
              }
            }
            return {
              fatal: null,
              executable: true,
              stepCount: this.steps,
              hookEnters: this.hookEnters,
              hookExits: this.hookExits,
              frameStack: this.frameStack,
              writes: this.writes,
              sha3s: this.sha3s,
              frames: outputFrames,
              observedStorage: observedStorage,
              observedStorageComplete: observedStorageComplete,
              lastOp: this.lastOp,
              lastDepth: this.lastDepth
            };
          }
        }
        """
        return (
            tracer.replace("__MAX_STEPS__", str(self.max_steps))
            .replace("__MAX_WRITES__", str(self.max_writes))
            .replace("__MAX_SHA3S__", str(self.max_sha3_ops))
            .replace("__MAX_SHA3_BYTES__", str(self.max_preimage_bytes))
            .replace("__MAX_OBSERVED_STORAGE__", str(self.max_observed_storage))
        )

    def _decode_compact_trace_result(
        self,
        result: Any,
    ) -> CompactTraceEvidence:
        if not isinstance(result, dict) or "fatal" not in result:
            raise ValueError("missing compact trace envelope")

        fatal = result["fatal"]
        if fatal is not None:
            if fatal in {
                "limit:steps",
                "limit:writes",
                "limit:sha3",
                "limit:preimage_bytes",
            }:
                raise TraceNotAvailableError("Trace exceeds configured limits")
            if fatal == "tracer:exception":
                raise ValueError("tracer callback failed")
            raise ValueError("unknown tracer fatal marker")

        executable = result.get("executable")
        if not isinstance(executable, bool):
            raise ValueError("invalid executable marker")
        step_count = self._strict_int(result.get("stepCount"), "stepCount")
        hook_enters = self._strict_int(result.get("hookEnters"), "hookEnters")
        hook_exits = self._strict_int(result.get("hookExits"), "hookExits")
        if step_count > self.max_steps:
            raise TraceNotAvailableError("Trace exceeds the configured step limit")
        if hook_enters != hook_exits:
            raise ValueError("unbalanced call hooks")

        frame_stack = result.get("frameStack")
        writes_value = result.get("writes")
        sha3s_value = result.get("sha3s")
        frames_value = result.get("frames")
        observed_storage_complete = result.get("observedStorageComplete")
        if not isinstance(observed_storage_complete, bool):
            raise ValueError("invalid observed-storage completeness marker")
        observed_storage = self._validate_observed_storage(
            result.get("observedStorage")
        )
        if not all(
            isinstance(value, list)
            for value in (frame_stack, writes_value, sha3s_value, frames_value)
        ):
            raise ValueError("compact trace collections must be arrays")

        if not executable:
            if (
                step_count != 0
                or hook_enters != 0
                or frame_stack
                or writes_value
                or sha3s_value
                or frames_value
                or observed_storage
                or not observed_storage_complete
            ):
                raise ValueError("no-op trace contains executable evidence")
            return CompactTraceEvidence(
                writes=[],
                sha3_operations=[],
                observed_storage={},
                observed_storage_complete=True,
                evm_step_count=0,
            )
        if frame_stack != [0]:
            raise ValueError("final frame stack is not root-only")
        if step_count == 0:
            raise ValueError("executable trace has no execution steps")
        last_op = result.get("lastOp")
        if not isinstance(last_op, str) or not last_op or len(last_op) > 64:
            raise ValueError("invalid final opcode")
        self._strict_int(result.get("lastDepth"), "lastDepth")

        frames = self._validate_compact_frames(frames_value)
        writes = self._validate_and_flatten_writes(
            writes_value,
            frames,
            step_count,
        )
        sha3s = self._validate_compact_sha3s(sha3s_value)
        self._validate_reduced_frame_graph(frames, writes)
        persistent_write_keys = {
            (write["address"], write["slot"])
            for write in writes
            if write["namespace"] == "persistent"
        }
        observed_keys = {
            (address, slot)
            for address, storage in observed_storage.items()
            for slot in storage
        }
        if observed_storage_complete:
            if any(
                value is None
                for storage in observed_storage.values()
                for value in storage.values()
            ):
                raise ValueError("complete observed storage contains null values")
            if not persistent_write_keys.issubset(observed_keys):
                raise ValueError(
                    "complete observed storage omitted a persistent write key"
                )

        logger.info(
            "Compact storage trace: steps=%s, writes=%s, sha3s=%s, last=%s@%s",
            step_count,
            len(writes),
            len(sha3s),
            result.get("lastOp"),
            result.get("lastDepth"),
        )
        return CompactTraceEvidence(
            writes=writes,
            sha3_operations=sha3s,
            observed_storage=observed_storage,
            observed_storage_complete=observed_storage_complete,
            evm_step_count=step_count,
        )

    def _validate_observed_storage(
        self,
        observed_value: Any,
    ) -> dict[str, dict[str, str | None]]:
        if not isinstance(observed_value, dict):
            raise ValueError("observed storage must be an object")
        observed: dict[str, dict[str, str | None]] = {}
        count = 0
        for raw_address, raw_storage in observed_value.items():
            if len(observed) >= self.max_prestate_accounts:
                raise TraceNotAvailableError(
                    "Trace exceeds the configured observed-account limit"
                )
            address = self._strict_address(
                raw_address,
                "observed_storage.address",
            )
            if address in observed:
                raise ValueError("duplicate observed-storage address")
            if not isinstance(raw_storage, dict):
                raise ValueError("observed account storage must be an object")
            if not raw_storage:
                raise ValueError("observed account storage must not be empty")
            storage: dict[str, str | None] = {}
            for raw_slot, raw_value in raw_storage.items():
                if not isinstance(raw_slot, str) or not re.fullmatch(
                    r"0x[0-9a-fA-F]{64}",
                    raw_slot,
                ):
                    raise ValueError("observed storage slot must be exactly 32 bytes")
                slot = raw_slot.lower()
                if slot in storage:
                    raise ValueError("duplicate observed-storage slot")
                if raw_value is None:
                    value = None
                elif isinstance(raw_value, str) and re.fullmatch(
                    r"0x[0-9a-fA-F]{64}",
                    raw_value,
                ):
                    value = raw_value.lower()
                else:
                    raise ValueError(
                        "observed storage value must be null or exactly 32 bytes"
                    )
                storage[slot] = value
                count += 1
                if count > self.max_observed_storage:
                    raise TraceNotAvailableError(
                        "Trace exceeds the configured observation limit"
                    )
            observed[address] = storage
        return observed

    def _validate_compact_frames(
        self,
        frames_value: list[Any],
    ) -> dict[int, dict]:
        frames: dict[int, dict] = {}
        allowed_types = {
            "ROOT",
            "CALL",
            "STATICCALL",
            "DELEGATECALL",
            "CALLCODE",
            "CREATE",
            "CREATE2",
        }
        for raw in frames_value:
            if not isinstance(raw, dict):
                raise ValueError("frame must be an object")
            frame_id = self._strict_int(raw.get("id"), "frame.id")
            if frame_id in frames:
                raise ValueError("duplicate frame id")
            parent_id = raw.get("parent_id")
            if parent_id is not None:
                parent_id = self._strict_int(parent_id, "frame.parent_id")
            frame_type = raw.get("type")
            if frame_type not in allowed_types:
                raise ValueError("unsupported frame type")
            depth = self._strict_int(raw.get("depth"), "frame.depth")
            storage = self._strict_address(
                raw.get("storage_address"),
                "frame.storage_address",
            )
            requested = self._strict_address(
                raw.get("requested_code_address"),
                "frame.requested_code_address",
            )
            target_confirmed = raw.get("target_confirmed")
            faulted = raw.get("faulted")
            completion_validated = raw.get("completion_validated")
            if not all(
                isinstance(value, bool)
                for value in (target_confirmed, faulted, completion_validated)
            ):
                raise ValueError("frame evidence flags must be booleans")
            if not target_confirmed:
                raise ValueError("returned frame target was not confirmed")
            outcome = raw.get("outcome")
            if outcome not in {"succeeded", "failed"}:
                raise ValueError("frame outcome is not terminal")
            exit_error = raw.get("exit_error")
            if exit_error is not None and (
                not isinstance(exit_error, str) or len(exit_error) > 4096
            ):
                raise ValueError("invalid frame exit error")

            attribution = raw.get("code_attribution")
            source = raw.get("code_source")
            designator = raw.get("code_designator")
            code_address = raw.get("code_address")
            if attribution == "exact":
                code_address = self._strict_address(
                    code_address,
                    "frame.code_address",
                )
                if source == "direct":
                    if code_address != requested or designator is not None:
                        raise ValueError("invalid direct code resolution")
                elif source == "eip7702":
                    if (
                        not isinstance(designator, str)
                        or not re.fullmatch(r"0xef0100[0-9a-fA-F]{40}", designator)
                        or code_address != "0x" + designator[8:].lower()
                    ):
                        raise ValueError("invalid EIP-7702 code resolution")
                    designator = designator.lower()
                else:
                    raise ValueError("invalid exact code source")
            elif attribution == "unknown":
                if (
                    code_address is not None
                    or source != "unknown"
                    or designator is not None
                ):
                    raise ValueError("invalid unknown code resolution")
            else:
                raise ValueError("invalid code attribution")

            completion_word = raw.get("completion_word")
            if frame_type == "ROOT":
                if (
                    frame_id != 0
                    or parent_id is not None
                    or not completion_validated
                    or completion_word is not None
                ):
                    raise ValueError("invalid root frame")
            else:
                if parent_id is None or not completion_validated:
                    raise ValueError("child completion was not validated")
                completion_word = self._strict_word(
                    completion_word,
                    "frame.completion_word",
                )
                failed = outcome == "failed"
                if frame_type in {
                    "CALL",
                    "STATICCALL",
                    "DELEGATECALL",
                    "CALLCODE",
                }:
                    if completion_word not in {
                        "0x" + "0" * 64,
                        "0x" + "0" * 63 + "1",
                    }:
                        raise ValueError("invalid call completion word")
                    if failed != (int(completion_word, 16) == 0):
                        raise ValueError("call outcome contradicts completion")
                    if failed != (faulted or exit_error is not None):
                        raise ValueError("call outcome contradicts exit evidence")
                else:
                    if int(completion_word, 16) == 0:
                        if not failed:
                            raise ValueError("creation failure marked successful")
                    else:
                        if (
                            failed
                            or self._word_address(completion_word) != requested
                            or faulted
                            or exit_error is not None
                        ):
                            raise ValueError(
                                "creation success contradicts completion"
                            )

            frames[frame_id] = {
                "id": frame_id,
                "parent_id": parent_id,
                "type": frame_type,
                "depth": depth,
                "storage_address": storage,
                "requested_code_address": requested,
                "code_address": code_address,
                "code_attribution": attribution,
                "code_source": source,
                "code_designator": designator,
                "faulted": faulted,
                "exit_error": exit_error,
                "outcome": outcome,
                "completion_word": completion_word,
            }

        if frames and 0 not in frames:
            raise ValueError("write frame graph has no root")
        for frame in frames.values():
            parent_id = frame["parent_id"]
            if parent_id is None:
                continue
            parent = frames.get(parent_id)
            if parent is None:
                raise ValueError("frame parent is missing")
            if frame["depth"] != parent["depth"] + 1:
                raise ValueError("frame depth does not follow its parent")
            if frame["type"] in {"DELEGATECALL", "CALLCODE"}:
                if frame["storage_address"] != parent["storage_address"]:
                    raise ValueError("delegate frame changed storage context")
            elif frame["storage_address"] != frame["requested_code_address"]:
                raise ValueError("call/create frame storage target mismatch")
        if frames:
            root = frames[0]
            if (
                root["type"] != "ROOT"
                or root["storage_address"] != root["requested_code_address"]
                or (root["outcome"] == "failed")
                != (root["faulted"] or root["exit_error"] is not None)
            ):
                raise ValueError("invalid root storage context")
        self._validate_acyclic_frames(frames)
        return frames

    def _validate_and_flatten_writes(
        self,
        writes_value: list[Any],
        frames: dict[int, dict],
        step_count: int,
    ) -> list[dict]:
        if len(writes_value) > self.max_writes:
            raise TraceNotAvailableError("Trace exceeds the configured write limit")
        writes = []
        previous_index = -1
        for raw in writes_value:
            if not isinstance(raw, dict):
                raise ValueError("write must be an object")
            frame_id = self._strict_int(raw.get("frame_id"), "write.frame_id")
            frame = frames.get(frame_id)
            if frame is None:
                raise ValueError("write references an unknown frame")
            index = self._strict_int(raw.get("index"), "write.index")
            if index <= previous_index or index >= step_count:
                raise ValueError("write index is outside execution order")
            previous_index = index
            pc = self._strict_int(raw.get("pc"), "write.pc")
            depth = self._strict_int(raw.get("depth"), "write.depth")
            if depth != frame["depth"]:
                raise ValueError("write depth contradicts its frame")
            opcode = raw.get("opcode")
            namespace = raw.get("namespace")
            if (opcode, namespace) not in {
                ("SSTORE", "persistent"),
                ("TSTORE", "transient"),
            }:
                raise ValueError("invalid storage-write opcode/namespace")
            if raw.get("old_value") is not None:
                raise ValueError("compact tracer must not guess old values")

            failed_ancestors = []
            current: int | None = frame_id
            while current is not None:
                current_frame = frames[current]
                if current_frame["outcome"] == "failed":
                    failed_ancestors.append(current)
                current = current_frame["parent_id"]
            writes.append(
                {
                    "address": frame["storage_address"],
                    "code_address": frame["code_address"],
                    "code_attribution": frame["code_attribution"],
                    "pc": pc,
                    "slot": self._strict_word(raw.get("slot"), "write.slot"),
                    "value": self._strict_word(raw.get("value"), "write.value"),
                    "old_value": None,
                    "opcode": opcode,
                    "namespace": namespace,
                    "depth": depth,
                    "index": index,
                    "frame_id": frame_id,
                    "frame_parent_id": frame["parent_id"],
                    "frame_failed": frame["outcome"] == "failed",
                    "frame_reverted": bool(failed_ancestors),
                    "rollback_frame_id": (
                        failed_ancestors[0] if failed_ancestors else None
                    ),
                    "rollback_parent_id": (
                        failed_ancestors[1]
                        if len(failed_ancestors) > 1
                        else None
                    ),
                }
            )
        return writes

    def _validate_compact_sha3s(
        self,
        sha3s_value: list[Any],
    ) -> list[dict]:
        if len(sha3s_value) > self.max_sha3_ops:
            raise TraceNotAvailableError("Trace exceeds the configured SHA3 limit")
        sha3s = []
        preimage_bytes = 0
        for raw in sha3s_value:
            if not isinstance(raw, dict):
                raise ValueError("SHA3 evidence must be an object")
            size = self._strict_int(raw.get("size"), "sha3.size")
            if not 32 <= size <= 256:
                raise ValueError("SHA3 evidence size is outside capture range")
            preimage = raw.get("preimage")
            if (
                not isinstance(preimage, str)
                or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})+", preimage)
                or (len(preimage) - 2) // 2 != size
            ):
                raise ValueError("invalid SHA3 preimage")
            preimage = preimage.lower()
            preimage_bytes += size
            if preimage_bytes > self.max_preimage_bytes:
                raise TraceNotAvailableError(
                    "Trace exceeds the configured preimage limit"
                )
            sha3s.append(
                {
                    "address": self._strict_address(
                        raw.get("address"),
                        "sha3.address",
                    ),
                    "preimage": preimage,
                    "hash": Web3.keccak(
                        bytes.fromhex(preimage.removeprefix("0x"))
                    ).hex(),
                    "size": size,
                    "depth": self._strict_int(raw.get("depth"), "sha3.depth"),
                }
            )
        return sha3s

    @staticmethod
    def _validate_acyclic_frames(frames: dict[int, dict]) -> None:
        for frame_id in frames:
            seen = set()
            current: int | None = frame_id
            while current is not None:
                if current in seen:
                    raise ValueError("frame graph contains a cycle")
                seen.add(current)
                current = frames[current]["parent_id"]

    @staticmethod
    def _validate_reduced_frame_graph(
        frames: dict[int, dict],
        writes: list[dict],
    ) -> None:
        needed = set()
        for write in writes:
            current: int | None = write["frame_id"]
            while current is not None:
                needed.add(current)
                current = frames[current]["parent_id"]
        if needed != set(frames):
            raise ValueError("frame response is not reduced to write ancestors")

    @staticmethod
    def _strict_int(value: Any, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} must be a nonnegative integer")
        return value

    @staticmethod
    def _strict_address(value: Any, field: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"0x[0-9a-fA-F]{40}",
            value,
        ):
            raise ValueError(f"{field} must be exactly 20 bytes")
        return value.lower()

    @staticmethod
    def _strict_word(value: Any, field: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"0x[0-9a-fA-F]{1,64}",
            value,
        ):
            raise ValueError(f"{field} must be a 256-bit word")
        return "0x" + value[2:].lower().zfill(64)

    @staticmethod
    def _word_address(word: str) -> str:
        return "0x" + word[-40:]

    def _validate_prestate_size(self, trace: dict) -> None:
        if not isinstance(trace, dict):
            raise TraceNotAvailableError("Prestate trace is malformed")

        sides = (
            (trace.get("pre", {}), trace.get("post", {}))
            if "pre" in trace or "post" in trace
            else (trace,)
        )
        account_count = 0
        storage_count = 0
        for accounts in sides:
            if not isinstance(accounts, dict):
                raise TraceNotAvailableError("Prestate trace is malformed")
            account_count += len(accounts)
            if account_count > self.max_prestate_accounts:
                raise TraceNotAvailableError(
                    "Prestate trace exceeds the configured account limit"
                )
            for state in accounts.values():
                if not isinstance(state, dict):
                    continue
                storage = state.get("storage", {})
                if isinstance(storage, dict):
                    storage_count += len(storage)
                if storage_count > self.max_prestate_storage_entries:
                    raise TraceNotAvailableError(
                        "Prestate trace exceeds the configured storage limit"
                    )
