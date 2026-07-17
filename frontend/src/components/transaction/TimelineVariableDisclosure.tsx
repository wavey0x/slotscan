'use client';

import type { ReactNode } from 'react';
import { ExternalLink } from 'lucide-react';
import { CopyButton } from '@/components/ui/CopyButton';
import { DetailPopover, DetailSection } from '@/components/ui/DetailPopover';
import { getAddressExplorerUrl } from '@/lib/constants';
import { contractDisplayLabel } from '@/lib/contract-resolution';
import type { ContractHistoryResponse } from '@/lib/types';
import { cn, truncateAddress } from '@/lib/utils';

function DetailAddress({
  address,
  chain,
  copyLabel,
  explorerLabel,
  prefix,
  subdued = false,
}: {
  address: string;
  chain: string;
  copyLabel: string;
  explorerLabel: string;
  prefix?: string;
  subdued?: boolean;
}) {
  return (
    <div className={cn('flex min-w-0 items-start gap-1', subdued && 'text-[10px]')}>
      {prefix && <span className="shrink-0 text-gray-500">{prefix}</span>}
      <a
        href={getAddressExplorerUrl(chain, address)}
        target="_blank"
        rel="noopener noreferrer"
        title={explorerLabel}
        className={cn(
          'flex min-w-0 flex-1 items-start gap-1 font-mono hover:text-gray-900 hover:underline',
          subdued ? 'text-gray-500' : 'text-gray-700',
        )}
      >
        <span className="min-w-0 break-all">{address}</span>
        <ExternalLink
          aria-hidden="true"
          size={subdued ? 10 : 11}
          strokeWidth={1.25}
          className="mt-0.5 shrink-0"
        />
      </a>
      <CopyButton
        value={address}
        label={copyLabel}
        className="-my-1 shrink-0"
      />
    </div>
  );
}

interface VariablePart {
  kind: 'name' | 'key';
  value: string;
}

function variableParts(variable: string): VariablePart[] {
  const parts: VariablePart[] = [];
  let cursor = 0;

  while (cursor < variable.length) {
    const open = variable.indexOf('[', cursor);
    if (open === -1) {
      parts.push({ kind: 'name', value: variable.slice(cursor) });
      break;
    }

    if (open > cursor) {
      parts.push({ kind: 'name', value: variable.slice(cursor, open) });
    }

    let depth = 1;
    let close = open + 1;
    while (close < variable.length && depth > 0) {
      if (variable[close] === '[') depth += 1;
      if (variable[close] === ']') depth -= 1;
      close += 1;
    }

    if (depth !== 0) {
      parts.push({ kind: 'name', value: variable.slice(open) });
      break;
    }

    parts.push({ kind: 'key', value: variable.slice(open, close) });
    cursor = close;
  }

  return parts;
}

function VariableDetailValue({
  variable,
  isRawSlot,
}: {
  variable: string;
  isRawSlot: boolean;
}) {
  if (isRawSlot) {
    return (
      <span
        className="min-w-0 break-all font-mono text-xs text-gray-700"
        data-testid="detail-variable-value"
      >
        {variable}
      </span>
    );
  }

  const parts = variableParts(variable);
  return (
    <span
      className="min-w-0 break-words font-mono text-sm leading-snug text-gray-900 [overflow-wrap:anywhere]"
      data-testid="detail-variable-value"
    >
      {parts.map((part, index) => (
        <span key={`${part.kind}:${index}`} className="contents">
          {index > 0 && <wbr />}
          <span
            className={part.kind === 'key' ? 'text-xs text-gray-500' : undefined}
            data-testid={part.kind === 'key' ? 'detail-variable-key' : 'detail-variable-name'}
          >
            {part.value}
          </span>
        </span>
      ))}
    </span>
  );
}

export function TimelineVariableDisclosure({
  children,
  contract,
  chain,
  variable,
  typeLabel,
  isRawSlot,
}: {
  children: ReactNode;
  contract: ContractHistoryResponse;
  chain: string;
  variable: string;
  typeLabel?: string | null;
  isRawSlot: boolean;
}) {
  const storageAddress = contract.storage_address;
  const implementationAddresses = Array.from(new Map(
    contract.implementation_addresses
      .filter((address) => address.toLowerCase() !== storageAddress.toLowerCase())
      .map((address) => [address.toLowerCase(), address]),
  ).values());

  return (
    <DetailPopover
      className="w-full max-w-full"
      contentClassName="w-[calc(100vw-1rem)] max-h-[calc(100vh-1rem)] overflow-y-auto"
      dialogLabel={`Variable details: ${variable}`}
      maxWidth="max-w-sm"
      content={(
        <div data-testid="timeline-variable-detail" className="min-w-0">
          <DetailSection title={isRawSlot ? 'Raw slot' : 'Variable'}>
            <div className="flex min-w-0 items-start gap-1">
              <VariableDetailValue variable={variable} isRawSlot={isRawSlot} />
              <CopyButton
                value={variable}
                label={isRawSlot ? 'Copy raw slot' : 'Copy full path'}
                className="-my-1 shrink-0"
              />
            </div>
            {typeLabel && (
              <div className="break-all font-mono text-[10px] text-gray-500">{typeLabel}</div>
            )}
          </DetailSection>

          <div className="my-1.5 border-t border-gray-200" />
          <DetailSection title="Contract">
            <div className="text-xs font-medium text-gray-900">{contractDisplayLabel(contract)}</div>
            <DetailAddress
              address={storageAddress}
              chain={chain}
              copyLabel="Copy storage contract address"
              explorerLabel="View storage contract on Etherscan"
            />
            {implementationAddresses.length > 0 && (
              <div className="mt-0.5 space-y-0.5">
                {implementationAddresses.map((address) => (
                  <DetailAddress
                    key={address}
                    address={address}
                    chain={chain}
                    copyLabel={`Copy implementation address ${truncateAddress(address)}`}
                    explorerLabel="View implementation on Etherscan"
                    prefix="via"
                    subdued
                  />
                ))}
              </div>
            )}
          </DetailSection>
        </div>
      )}
    >
      {children}
    </DetailPopover>
  );
}
