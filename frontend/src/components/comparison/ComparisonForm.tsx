'use client';

import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowLeftRight } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import type { LayoutComparisonRequest } from '@/lib/types';

export interface ComparisonUrlState {
  from: string;
  to: string;
  fromBlock: string;
  fromBlockHash: string;
  toBlock: string;
  toBlockHash: string;
}

const ADDRESS_PATTERN = /^0x[0-9a-fA-F]{40}$/;
const BLOCK_PATTERN = /^(0|[1-9][0-9]*)$/;
const BLOCK_HASH_PATTERN = /^0x[0-9a-fA-F]{64}$/;

function validAddress(value: string): boolean {
  return ADDRESS_PATTERN.test(value.trim());
}

function validBlock(value: string): boolean {
  return !value.trim() || BLOCK_PATTERN.test(value.trim());
}

function validBlockHash(value: string): boolean {
  return !value.trim() || BLOCK_HASH_PATTERN.test(value.trim());
}

export function requestFromUrlState(
  state: ComparisonUrlState,
): LayoutComparisonRequest | null {
  if (!validAddress(state.from) || !validAddress(state.to)) return null;
  if (!validBlock(state.fromBlock) || !validBlock(state.toBlock)) return null;
  if (!validBlockHash(state.fromBlockHash) || !validBlockHash(state.toBlockHash)) {
    return null;
  }
  if (state.fromBlockHash && !state.fromBlock) return null;
  if (state.toBlockHash && !state.toBlock) return null;
  return {
    fromAddress: state.from,
    toAddress: state.to,
    ...(state.fromBlock ? { fromBlock: state.fromBlock } : {}),
    ...(state.fromBlockHash ? { fromBlockHash: state.fromBlockHash } : {}),
    ...(state.toBlock ? { toBlock: state.toBlock } : {}),
    ...(state.toBlockHash ? { toBlockHash: state.toBlockHash } : {}),
  };
}

function initialErrors(state: ComparisonUrlState) {
  return {
    from: state.from && !validAddress(state.from) ? 'Enter a valid Ethereum address.' : '',
    to: state.to && !validAddress(state.to) ? 'Enter a valid Ethereum address.' : '',
    fromBlock: !validBlock(state.fromBlock)
      ? 'Use a non-negative decimal block number.'
      : !validBlockHash(state.fromBlockHash)
        ? 'The exact block hash is invalid; edit this block to refresh it.'
      : state.fromBlockHash && !state.fromBlock
        ? 'The exact hash requires a block number.'
        : '',
    toBlock: !validBlock(state.toBlock)
      ? 'Use a non-negative decimal block number.'
      : !validBlockHash(state.toBlockHash)
        ? 'The exact block hash is invalid; edit this block to refresh it.'
      : state.toBlockHash && !state.toBlock
        ? 'The exact hash requires a block number.'
        : '',
  };
}

export function ComparisonForm({
  submitted,
  onSubmit,
}: {
  submitted: ComparisonUrlState;
  onSubmit: (state: ComparisonUrlState) => void;
}) {
  const [draft, setDraft] = useState(submitted);
  const [errors, setErrors] = useState(() => initialErrors(submitted));
  const [blocksOpen, setBlocksOpen] = useState(
    Boolean(
      submitted.fromBlock
      || submitted.fromBlockHash
      || submitted.toBlock
      || submitted.toBlockHash
    ),
  );
  const fromRef = useRef<HTMLInputElement>(null);
  const toRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setDraft(submitted);
    setErrors(initialErrors(submitted));
    if (
      submitted.fromBlock
      || submitted.fromBlockHash
      || submitted.toBlock
      || submitted.toBlockHash
    ) {
      setBlocksOpen(true);
    }
    requestAnimationFrame(() => {
      if (submitted.from && !submitted.to) toRef.current?.focus();
      else if (!submitted.from) fromRef.current?.focus();
    });
  }, [submitted]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const nextErrors = initialErrors(draft);
    if (!draft.from) nextErrors.from = 'Enter a From address.';
    if (!draft.to) nextErrors.to = 'Enter a To address.';
    setErrors(nextErrors);
    if (Object.values(nextErrors).some(Boolean)) return;
    onSubmit({
      ...draft,
      from: draft.from.trim(),
      to: draft.to.trim(),
      fromBlock: draft.fromBlock.trim(),
      toBlock: draft.toBlock.trim(),
    });
  };

  const setAddress = (side: 'from' | 'to', value: string) => {
    setDraft((current) => ({
      ...current,
      [side]: value,
      [side === 'from' ? 'fromBlockHash' : 'toBlockHash']: '',
    }));
    setErrors((current) => ({ ...current, [side]: '' }));
  };

  const setBlock = (side: 'from' | 'to', value: string) => {
    const blockKey = side === 'from' ? 'fromBlock' : 'toBlock';
    const hashKey = side === 'from' ? 'fromBlockHash' : 'toBlockHash';
    setDraft((current) => ({
      ...current,
      [blockKey]: value,
      [hashKey]: '',
    }));
    setErrors((current) => ({ ...current, [blockKey]: '' }));
  };

  const swap = () => {
    setDraft((current) => ({
      from: current.to,
      to: current.from,
      fromBlock: current.toBlock,
      fromBlockHash: current.toBlockHash,
      toBlock: current.fromBlock,
      toBlockHash: current.fromBlockHash,
    }));
    setErrors({ from: '', to: '', fromBlock: '', toBlock: '' });
  };

  return (
    <form onSubmit={submit} noValidate>
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-end">
        <div className="block min-w-0">
          <label
            htmlFor="comparison-from-address"
            className="mb-1 block text-[10px] uppercase tracking-wide text-gray-500"
          >
            From
          </label>
          <Input
            id="comparison-from-address"
            ref={fromRef}
            value={draft.from}
            onChange={(event) => setAddress('from', event.target.value)}
            placeholder="contract, proxy, or account"
            aria-invalid={Boolean(errors.from)}
            aria-describedby={errors.from ? 'from-address-error' : undefined}
            className="font-mono text-xs"
          />
          {errors.from && (
            <span id="from-address-error" className="mt-1 block text-xs text-red">
              {errors.from}
            </span>
          )}
        </div>
        <span aria-hidden="true" className="hidden pb-2 text-gray-400 md:block">
          →
        </span>
        <div className="block min-w-0">
          <label
            htmlFor="comparison-to-address"
            className="mb-1 block text-[10px] uppercase tracking-wide text-gray-500"
          >
            To
          </label>
          <Input
            id="comparison-to-address"
            ref={toRef}
            value={draft.to}
            onChange={(event) => setAddress('to', event.target.value)}
            placeholder="contract, proxy, or account"
            aria-invalid={Boolean(errors.to)}
            aria-describedby={errors.to ? 'to-address-error' : undefined}
            className="font-mono text-xs"
          />
          {errors.to && (
            <span id="to-address-error" className="mt-1 block text-xs text-red">
              {errors.to}
            </span>
          )}
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <Button type="button" variant="secondary" onClick={swap}>
          <ArrowLeftRight aria-hidden="true" size={14} className="mr-2" />
          Swap
        </Button>
        <Button type="submit">Compare layouts</Button>
      </div>

      <div className="mt-4 border-t border-gray-200 pt-3">
        <button
          type="button"
          aria-expanded={blocksOpen}
          onClick={() => setBlocksOpen((open) => !open)}
          className="text-xs text-gray-500 hover:text-gray-900"
        >
          {blocksOpen ? 'Hide' : 'Resolve at'} specific blocks
          <span className="ml-1 text-[10px]" aria-hidden="true">
            {blocksOpen ? '−' : '+'}
          </span>
        </button>
        {blocksOpen && (
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <div>
              <label
                htmlFor="comparison-from-block"
                className="mb-1 block text-[10px] uppercase tracking-wide text-gray-500"
              >
                From block
              </label>
              <Input
                id="comparison-from-block"
                inputMode="numeric"
                value={draft.fromBlock}
                onChange={(event) => setBlock('from', event.target.value)}
                placeholder="Latest"
                aria-invalid={Boolean(errors.fromBlock)}
                aria-describedby={
                  errors.fromBlock ? 'from-block-error' : undefined
                }
                className="font-mono text-xs"
              />
              {errors.fromBlock && (
                <span
                  id="from-block-error"
                  className="mt-1 block text-xs text-red"
                >
                  {errors.fromBlock}
                </span>
              )}
            </div>
            <div>
              <label
                htmlFor="comparison-to-block"
                className="mb-1 block text-[10px] uppercase tracking-wide text-gray-500"
              >
                To block
              </label>
              <Input
                id="comparison-to-block"
                inputMode="numeric"
                value={draft.toBlock}
                onChange={(event) => setBlock('to', event.target.value)}
                placeholder="Latest"
                aria-invalid={Boolean(errors.toBlock)}
                aria-describedby={
                  errors.toBlock ? 'to-block-error' : undefined
                }
                className="font-mono text-xs"
              />
              {errors.toBlock && (
                <span
                  id="to-block-error"
                  className="mt-1 block text-xs text-red"
                >
                  {errors.toBlock}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
      <p className="mt-4 text-xs text-gray-500">
        Checks whether To can interpret storage described by From.
      </p>
    </form>
  );
}
