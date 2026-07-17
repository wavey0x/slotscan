'use client';

import { useState } from 'react';
import { Check, Copy, RefreshCw } from 'lucide-react';
import { ComparisonTable } from '@/components/comparison/ComparisonTable';
import { CopyButton } from '@/components/ui/CopyButton';
import { getAddressExplorerUrl, getBlockExplorerUrl } from '@/lib/constants';
import type {
  LayoutComparisonResponse,
  ResolvedLayoutSubject,
} from '@/lib/types';
import { truncateAddress } from '@/lib/utils';

const VERDICTS = {
  no_conflicts: 'No storage conflicts',
  conflicts: 'Storage conflicts found',
  indeterminate: 'Comparison indeterminate',
  unavailable: 'Comparison unavailable',
} as const;

const STATUS = {
  ok: 'Exact Solidity layout',
  unverified: 'Published source unavailable',
  unsupported: 'Unsupported layout',
  non_exact: 'Layout evidence is not exact',
  not_contract: 'No contract code',
  invalid_layout: 'Invalid compiler layout',
} as const;

const LIMITATIONS: Record<string, string> = {
  from_unverified: 'The From address has no verified source layout.',
  to_unverified: 'The To address has no verified source layout.',
  from_unsupported: 'The From address does not expose a supported exact Solidity layout.',
  to_unsupported: 'The To address does not expose a supported exact Solidity layout.',
  from_non_exact: 'The From layout depends on inferred or non-exact evidence.',
  to_non_exact: 'The To layout depends on inferred or non-exact evidence.',
  from_not_contract: 'The From address has no supported contract code at this block.',
  to_not_contract: 'The To address has no supported contract code at this block.',
  from_invalid_layout: 'The From compiler layout is structurally invalid.',
  to_invalid_layout: 'The To compiler layout is structurally invalid.',
  unsupported_language: 'Only exact Solidity layouts are supported.',
  unsupported_storage_rules: 'The declared storage rules are unsupported.',
  non_exact_layout: 'One or both layouts contain non-exact evidence.',
  invalid_layout: 'One or both compiler layouts are structurally invalid.',
  analysis_limit: 'The complete exact comparison exceeded a bounded analysis limit.',
};

function addressLink(chain: string, address: string, label: string) {
  return (
    <span className="inline-flex items-center gap-0.5">
      <a
        href={getAddressExplorerUrl(chain, address)}
        target="_blank"
        rel="noopener noreferrer"
        title={address}
      >
        {truncateAddress(address)}
      </a>
      <CopyButton value={address} label={label} className="-my-1" />
    </span>
  );
}

function Subject({
  side,
  chain,
  subject,
}: {
  side: 'From' | 'To';
  chain: string;
  subject: ResolvedLayoutSubject | null;
}) {
  if (!subject) {
    return (
      <div>
        <div className="text-[10px] uppercase tracking-wide text-gray-500">{side}</div>
        <div className="mt-2 text-xs text-gray-500">Resolution unavailable</div>
      </div>
    );
  }
  const block = BigInt(subject.block_ref.number).toString();
  const direct = subject.kind === 'direct';
  return (
    <div className="min-w-0">
      <div className="text-[10px] uppercase tracking-wide text-gray-500">{side}</div>
      <div className="mt-1 text-sm text-gray-900">
        {subject.name || (
          direct
            ? truncateAddress(subject.input_address)
            : subject.kind === 'proxy' ? 'Proxy' : 'EIP-7702'
        )}
      </div>
      <dl className="mt-2 space-y-1 text-xs">
        {direct ? (
          <div className="flex gap-2">
            <dt className="w-16 shrink-0 text-gray-500">Contract</dt>
            <dd>{addressLink(chain, subject.input_address, `Copy ${side} contract address`)}</dd>
          </div>
        ) : (
          <>
            <div className="flex gap-2">
              <dt className="w-16 shrink-0 text-gray-500">Storage</dt>
              <dd>{addressLink(chain, subject.storage_address, `Copy ${side} storage address`)}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-16 shrink-0 text-gray-500">Code</dt>
              <dd>{addressLink(chain, subject.code_address, `Copy ${side} code address`)}</dd>
            </div>
          </>
        )}
      </dl>
      <div className="mt-2 text-xs text-gray-700">{STATUS[subject.layout_status]}</div>
      <div className="mt-1 text-[10px] text-gray-500">
        Block{' '}
        <a
          href={getBlockExplorerUrl(chain, block)}
          target="_blank"
          rel="noopener noreferrer"
          title={subject.block_ref.hash}
        >
          {BigInt(block).toLocaleString()}
        </a>
      </div>
    </div>
  );
}

function exactUrl(report: LayoutComparisonResponse): string | null {
  if (!report.from_subject || !report.to_subject) return null;
  const params = new URLSearchParams();
  params.set('from', report.from_subject.input_address);
  params.set('to', report.to_subject.input_address);
  params.set('fromBlock', BigInt(report.from_subject.block_ref.number).toString());
  params.set('fromBlockHash', report.from_subject.block_ref.hash);
  params.set('toBlock', BigInt(report.to_subject.block_ref.number).toString());
  params.set('toBlockHash', report.to_subject.block_ref.hash);
  return `${window.location.origin}/${report.chain_id}/compare?${params}`;
}

export function ComparisonResult({
  chain,
  report,
  refreshing,
  refreshFailed,
  onRetry,
}: {
  chain: string;
  report: LayoutComparisonResponse;
  refreshing: boolean;
  refreshFailed: boolean;
  onRetry: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const copyExact = async () => {
    const url = exactUrl(report);
    if (!url) return;
    await navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  const counts = report.summary
    ? [
        report.summary.changes ? `${report.summary.changes} changes` : null,
        report.summary.conflicts ? `${report.summary.conflicts} conflicts` : null,
        report.summary.ambiguous ? `${report.summary.ambiguous} ambiguous` : null,
        `${report.summary.unchanged} unchanged`,
      ].filter(Boolean).join(' · ')
    : null;

  return (
    <div className="mt-9 border-t border-gray-300 pt-6">
      <div className="grid gap-5 sm:grid-cols-2">
        <Subject side="From" chain={chain} subject={report.from_subject} />
        <Subject side="To" chain={chain} subject={report.to_subject} />
      </div>

      <div className="mt-6 border-y border-gray-300 py-4" aria-live="polite">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-base">{VERDICTS[report.verdict]}</h2>
            {counts && <div className="mt-1 text-xs text-gray-500">{counts}</div>}
          </div>
          <div className="flex items-center gap-3 text-xs">
            {refreshing && <span className="text-gray-500">Refreshing…</span>}
            {refreshFailed && (
              <button type="button" onClick={onRetry} className="inline-flex items-center text-red">
                <RefreshCw aria-hidden="true" size={12} className="mr-1" />
                Retry
              </button>
            )}
            {report.from_subject && report.to_subject && (
              <button
                type="button"
                onClick={() => { void copyExact(); }}
                className="inline-flex items-center text-gray-700 hover:text-gray-900"
              >
                {copied
                  ? <Check aria-hidden="true" size={12} className="mr-1 text-green" />
                  : <Copy aria-hidden="true" size={12} className="mr-1" />}
                {copied ? 'Exact link copied' : 'Copy exact link'}
              </button>
            )}
          </div>
        </div>
        {report.limitations.length > 0 && (
          <ul className="mt-3 space-y-1 text-xs text-red">
            {report.limitations.map((code) => (
              <li key={code}>{LIMITATIONS[code] || `Comparison limitation: ${code}`}</li>
            ))}
          </ul>
        )}
        {report.verdict !== 'unavailable' && (
          <p className="mt-4 max-w-4xl text-xs text-gray-500">
            This report covers exact declared persistent storage layouts only.
            It does not analyze values, initialization, authorization,
            downstream calls, or overall safety.
          </p>
        )}
      </div>

      {report.summary && <ComparisonTable entries={report.entries} />}
    </div>
  );
}
