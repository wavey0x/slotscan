'use client';

import type { ReactNode } from 'react';
import { ExternalLink } from 'lucide-react';
import { CopyButton } from '@/components/ui/CopyButton';
import { DetailDivider, DetailPopover, DetailSection } from '@/components/ui/DetailPopover';
import { getAddressExplorerUrl } from '@/lib/constants';
import { contractDisplayLabel } from '@/lib/contract-resolution';
import type { ContractHistoryResponse } from '@/lib/types';
import { truncateAddress } from '@/lib/utils';

function DetailAddress({
  address,
  chain,
  copyLabel,
  explorerLabel,
}: {
  address: string;
  chain: string;
  copyLabel: string;
  explorerLabel: string;
}) {
  return (
    <div className="flex min-w-0 items-start gap-1">
      <a
        href={getAddressExplorerUrl(chain, address)}
        target="_blank"
        rel="noopener noreferrer"
        title={explorerLabel}
        className="flex min-w-0 flex-1 items-start gap-1 font-mono text-gray-200 hover:text-white hover:underline"
      >
        <span className="min-w-0 break-all">{address}</span>
        <ExternalLink aria-hidden="true" size={11} strokeWidth={1.25} className="mt-0.5 shrink-0" />
      </a>
      <CopyButton
        value={address}
        label={copyLabel}
        className="-my-1 shrink-0 hover:text-white focus-visible:text-white"
      />
    </div>
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
            <div className="flex min-w-0 items-start gap-1 border-l-2 border-gray-600 pl-2">
              <span className="min-w-0 break-all font-mono text-sm text-white">{variable}</span>
              <CopyButton
                value={variable}
                label={isRawSlot ? 'Copy raw slot' : 'Copy full path'}
                className="-my-1 shrink-0 hover:text-white focus-visible:text-white"
              />
            </div>
            {typeLabel && (
              <div className="flex items-baseline gap-2 text-[10px]">
                <span className="text-gray-400">Type</span>
                <span className="break-all font-mono text-gray-200">{typeLabel}</span>
              </div>
            )}
          </DetailSection>

          <DetailDivider />
          <DetailSection title="Contract">
            <div className="text-sm font-medium text-white">{contractDisplayLabel(contract)}</div>
            <DetailAddress
              address={storageAddress}
              chain={chain}
              copyLabel="Copy storage contract address"
              explorerLabel="View storage contract on Etherscan"
            />
          </DetailSection>

          {implementationAddresses.length > 0 && (
            <>
              <DetailDivider />
              <DetailSection title="Written via" className="space-y-1.5">
                {implementationAddresses.map((address) => (
                  <DetailAddress
                    key={address}
                    address={address}
                    chain={chain}
                    copyLabel={`Copy implementation address ${truncateAddress(address)}`}
                    explorerLabel="View implementation on Etherscan"
                  />
                ))}
              </DetailSection>
            </>
          )}
        </div>
      )}
    >
      {children}
    </DetailPopover>
  );
}
