'use client';

import { useEffect, useState } from 'react';
import { EntityHeader } from '@/components/layout/EntityHeader';
import { LayoutTable } from '@/components/layout/LayoutTable';
import { CopyButton } from '@/components/ui/CopyButton';
import { Loading } from '@/components/ui/Loading';
import { ViewSwitch } from '@/components/ui/ViewSwitch';
import { APIError } from '@/lib/api';
import { getAddressExplorerUrl, getBlockExplorerUrl } from '@/lib/constants';
import { useStorageView } from '@/lib/hooks/useStorageView';
import { truncateAddress, truncateHash, updateRecentSearchName } from '@/lib/utils';

interface ContractPageProps {
  chain: string;
  address: string;
}

function addressLink(chain: string, value: string, copyLabel: string) {
  return (
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
}

export function ContractPage({ chain, address }: ContractPageProps) {
  const {
    data: view,
    isLoading,
    isFetching,
    error,
  } = useStorageView(chain, address, 'latest');
  const [showHex, setShowHex] = useState(false);
  const contract = view?.contract;
  const displayName = contract?.name || null;

  useEffect(() => {
    if (displayName) {
      updateRecentSearchName(chain, address, displayName);
    }
  }, [address, chain, displayName]);

  if (isLoading && !view) {
    return <Loading message="Loading storage layout" />;
  }

  if (!view) {
    const message = error instanceof APIError
      ? error.message
      : 'The contract storage view could not be loaded.';
    return (
      <div className="border border-gray-300 p-5">
        <div className="mb-1 text-sm text-gray-900">Storage view unavailable</div>
        <p className="text-xs text-gray-500">{message}</p>
      </div>
    );
  }

  const isDelegated = !contract!.is_proxy
    && contract!.effective_code_address.toLowerCase() !== contract!.storage_address.toLowerCase();
  const statuses = [
    isDelegated ? 'Delegated EOA' : null,
    contract!.is_proxy ? 'Proxy' : null,
    contract!.is_verified ? 'Verified' : 'Unverified',
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
  const metadata = isDelegated ? (
    <span className="flex flex-wrap gap-x-5 gap-y-1">
      <span>Storage at {addressLink(chain, contract!.storage_address, 'Copy storage address')}</span>
      <span>
        Executing code from{' '}
        {addressLink(chain, contract!.effective_code_address, 'Copy delegate address')}
      </span>
    </span>
  ) : contract!.is_proxy ? (
    <span>
      Implementation{' '}
      {addressLink(chain, contract!.effective_code_address, 'Copy implementation address')}
    </span>
  ) : undefined;
  const blockNumber = BigInt(view.block_ref.number).toString();

  return (
    <>
      <EntityHeader
        kind="addr"
        title={displayName || addressIdentifier}
        identifier={displayName ? addressIdentifier : undefined}
        status={statuses.join(' · ')}
        meta={metadata}
      />

      <section>
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-base font-medium text-gray-900">Storage layout</h2>
            <div className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-1 text-[10px] text-gray-500">
              <span>
                Block{' '}
                <a
                  href={getBlockExplorerUrl(chain, blockNumber)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {BigInt(blockNumber).toLocaleString()}
                </a>
              </span>
              <span className="inline-flex items-center gap-0.5" title={view.block_ref.hash}>
                Hash {truncateHash(view.block_ref.hash, 6)}
                <CopyButton value={view.block_ref.hash} label="Copy block hash" className="-my-1" />
              </span>
              <span>{view.layout.variables.length} variables</span>
              {isFetching && <span>Refreshing…</span>}
              {error && <span className="text-red">Refresh failed · showing last exact block</span>}
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

        {view.layout.status !== 'ok' || !view.layout_id ? (
          <div className="border border-gray-300 p-5">
            <div className="mb-1 text-sm text-gray-900">Storage layout unavailable</div>
            <p className="text-xs text-gray-500">
              {view.layout.status === 'unverified'
                ? 'Published source code is unavailable for this contract.'
                : 'The published source could not produce a supported storage layout.'}
            </p>
          </div>
        ) : (
          <>
            {view.values.status === 'error' && (
              <div className="mb-3 border border-red/30 p-3 text-xs text-red">
                Values could not be read at this block. The verified layout remains available.
              </div>
            )}
            <LayoutTable
              key={view.block_ref.hash}
              chainId={chain}
              address={address}
              blockRef={view.block_ref}
              layoutId={view.layout_id}
              layout={view.layout}
              values={view.values.items}
              showHex={showHex}
            />
          </>
        )}
      </section>
    </>
  );
}
