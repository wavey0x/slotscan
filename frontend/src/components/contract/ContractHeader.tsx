'use client';

import { useContract } from '@/lib/hooks/useContract';
import { truncateAddress } from '@/lib/utils';
import { getChainName } from '@/lib/constants';
import { Badge } from '@/components/ui/Badge';
import { useState } from 'react';

interface ContractHeaderProps {
  chainId: string;
  address: string;
}

function CopyIcon({ className }: { className?: string }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      className={className}
    >
      <rect x="4.5" y="4.5" width="8" height="8" />
      <path d="M9.5 4.5V1.5H1.5V9.5H4.5" />
    </svg>
  );
}

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="square"
      className={className}
    >
      <path d="M2 7L5.5 10.5L12 4" />
    </svg>
  );
}

export function ContractHeader({ chainId, address }: ContractHeaderProps) {
  const { data, isLoading, error } = useContract(chainId, address);
  const [copied, setCopied] = useState(false);

  const copyAddress = async () => {
    await navigator.clipboard.writeText(address);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (isLoading) {
    return (
      <div className="mb-8 py-4 border-b border-gray-300">
        <div className="flex items-center gap-2">
          <span className="text-gray-500">Loading contract</span>
          <span className="inline-flex w-6">
            <span className="animate-[blink_1.4s_ease-in-out_infinite]">.</span>
            <span className="animate-[blink_1.4s_ease-in-out_0.2s_infinite]">.</span>
            <span className="animate-[blink_1.4s_ease-in-out_0.4s_infinite]">.</span>
          </span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mb-8 py-4 border-b border-gray-300">
        <h1 className="text-lg text-gray-900 mb-1">
          {truncateAddress(address)}
        </h1>
        <p className="text-sm text-red">{(error as Error).message}</p>
      </div>
    );
  }

  const etherscanUrl = `https://etherscan.io/address/${address}`;

  return (
    <div className="mb-8 py-4 border-b border-gray-300">
      <div className="flex items-center gap-3 mb-2">
        <h1 className="text-lg text-gray-900">
          {data?.name || truncateAddress(address)}
        </h1>
        {data?.is_proxy && (
          <Badge>Proxy</Badge>
        )}
        {data?.is_verified ? (
          <Badge variant="success">Verified</Badge>
        ) : (
          <Badge>Unverified</Badge>
        )}
      </div>

      <div className="group inline-flex items-center gap-2 text-sm text-gray-700 relative px-2 py-1 rounded-md transition border border-transparent hover:border-dashed hover:border-gray-400">
        <a
          href={etherscanUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="font-mono text-gray-900 hover:underline"
        >
          {address}
        </a>
        <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={copyAddress}
            className="p-1 hover:text-gray-900 transition-colors"
            title="Copy address"
          >
            {copied ? (
              <CheckIcon className="text-green" />
            ) : (
              <CopyIcon />
            )}
          </button>
        </div>
      </div>

      <div className="text-xs text-gray-500 mt-2 font-mono">
        {getChainName(chainId)}
        {data?.implementation_address && (
          <span className="ml-3">
            impl: {truncateAddress(data.implementation_address)}
          </span>
        )}
      </div>
    </div>
  );
}
