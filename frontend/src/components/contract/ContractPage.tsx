'use client';

import { useEffect, useState } from 'react';
import { EntityHeader } from '@/components/layout/EntityHeader';
import { LayoutTable } from '@/components/layout/LayoutTable';
import { CopyButton } from '@/components/ui/CopyButton';
import { Loading } from '@/components/ui/Loading';
import { ViewSwitch } from '@/components/ui/ViewSwitch';
import { APIError } from '@/lib/api';
import { getAddressExplorerUrl, getBlockExplorerUrl } from '@/lib/constants';
import { useContract } from '@/lib/hooks/useContract';
import { useLayout } from '@/lib/hooks/useLayout';
import { useStorage } from '@/lib/hooks/useStorage';
import { truncateAddress, updateRecentSearchName } from '@/lib/utils';

interface ContractPageProps {
  chain: string;
  address: string;
}

function LayoutError({ error, chain }: { error: Error; chain: string }) {
  const apiError = error instanceof APIError ? error : null;
  const details = apiError?.details as Record<string, string> | undefined;

  if (apiError?.code === 'DELEGATE_LAYOUT_UNAVAILABLE' && details?.delegate_address) {
    return (
      <div className="border border-gray-300 p-5">
        <div className="mb-1 text-sm text-gray-900">Delegated code layout unavailable</div>
        <p className="text-xs text-gray-500">
          The code source at{' '}
          <span className="inline-flex items-center gap-0.5">
            <a
              href={getAddressExplorerUrl(chain, details.delegate_address)}
              target="_blank"
              rel="noopener noreferrer"
              title={details.delegate_address}
            >
              {truncateAddress(details.delegate_address)}
            </a>
            <CopyButton value={details.delegate_address} label="Copy delegate address" className="-my-1" />
          </span>{' '}
          does not have a usable published storage layout.
        </p>
      </div>
    );
  }

  if (apiError?.code === 'PROXY_IMPL_NOT_VERIFIED' && details?.implementation_address) {
    return (
      <div className="border border-gray-300 p-5">
        <div className="mb-1 text-sm text-gray-900">Implementation not verified</div>
        <p className="text-xs text-gray-500">
          The proxy implementation does not have a published storage layout.{' '}
          <span className="inline-flex items-center gap-0.5">
            <a
              href={getAddressExplorerUrl(chain, details.implementation_address)}
              target="_blank"
              rel="noopener noreferrer"
              title={details.implementation_address}
            >
              {truncateAddress(details.implementation_address)}
            </a>
            <CopyButton value={details.implementation_address} label="Copy implementation address" className="-my-1" />
          </span>
        </p>
      </div>
    );
  }

  const message = apiError?.code === 'NOT_VERIFIED'
    ? 'Published source code is unavailable for this contract.'
    : apiError?.code === 'UNSUPPORTED_COMPILER_VERSION'
      ? `Storage layout output is unavailable for Solidity ${details?.compiler_version || 'versions before 0.5.13'}.`
      : apiError?.message || 'The storage layout could not be loaded.';

  return (
    <div className="border border-gray-300 p-5">
      <div className="mb-1 text-sm text-gray-900">Storage layout unavailable</div>
      <p className="text-xs text-gray-500">{message}</p>
    </div>
  );
}

export function ContractPage({ chain, address }: ContractPageProps) {
  const { data: contract } = useContract(chain, address);
  const { data: layout, isLoading, error } = useLayout(chain, address);
  const { data: storage } = useStorage(chain, address, 'latest');
  const [showHex, setShowHex] = useState(false);
  const displayName = contract?.name || layout?.contract_name || null;

  useEffect(() => {
    if (displayName) {
      updateRecentSearchName(chain, address, displayName);
    }
  }, [address, chain, displayName]);

  const statuses = [
    contract?.is_delegated ? 'Delegated EOA' : null,
    contract?.is_proxy ? 'Proxy' : null,
    contract ? (contract.is_verified ? 'Verified' : 'Unverified') : null,
  ].filter(Boolean);

  const addressIdentifier = (
    <span className="inline-flex min-w-0 items-center gap-0.5">
      <a
        href={getAddressExplorerUrl(chain, address)}
        target="_blank"
        rel="noopener noreferrer"
        className="truncate font-mono"
        title={address}
      >
        {truncateAddress(address)}
      </a>
      <CopyButton value={address} label="Copy contract address" />
    </span>
  );
  const addressLink = (value: string, copyLabel: string) => (
    <span className="inline-flex items-center gap-0.5">
      <a
        href={getAddressExplorerUrl(chain, value)}
        target="_blank"
        rel="noopener noreferrer"
        title={value}
      >
        {truncateAddress(value)}
      </a>
      <CopyButton value={value} label={copyLabel} className="-my-1" />
    </span>
  );
  const metadata = contract?.is_delegated && contract.delegate_address ? (
    <span className="flex flex-wrap gap-x-5 gap-y-1">
      <span>Storage at {addressLink(address, 'Copy storage address')}</span>
      <span>Executing code from {addressLink(contract.delegate_address, 'Copy delegate address')}</span>
    </span>
  ) : contract?.implementation_address ? (
    <span className="inline-flex items-center gap-0.5">
      <span>Implementation</span>
      {addressLink(contract.implementation_address, 'Copy implementation address')}
    </span>
  ) : undefined;

  return (
    <>
      <EntityHeader
        kind="addr"
        title={displayName || addressIdentifier}
        identifier={displayName ? addressIdentifier : undefined}
        status={statuses.length > 0 ? statuses.join(' · ') : undefined}
        meta={metadata}
      />

      {isLoading ? (
        <Loading message="Loading storage layout" />
      ) : error ? (
        <LayoutError error={error as Error} chain={chain} />
      ) : !layout ? (
        <div className="border border-gray-300 p-5 text-xs text-gray-500">No storage layout available.</div>
      ) : (
        <section>
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-base font-medium text-gray-900">Storage layout</h2>
              <div className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-1 text-[10px] text-gray-500">
                {storage?.block_number && (
                  <span>
                    Block{' '}
                    <a
                      href={getBlockExplorerUrl(chain, storage.block_number)}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {storage.block_number.toLocaleString()}
                    </a>
                  </span>
                )}
                <span>{layout.variables.length} variables</span>
              </div>
            </div>
            <ViewSwitch
              label="Values"
              value={showHex ? 'hex' : 'decoded'}
              options={[
                { value: 'decoded', label: 'Decoded' },
                { value: 'hex', label: 'Hex' },
              ]}
              onChange={(value) => setShowHex(value === 'hex')}
              showLabel={false}
            />
          </div>
          <LayoutTable chainId={chain} address={address} layout={layout} showHex={showHex} />
        </section>
      )}
    </>
  );
}
