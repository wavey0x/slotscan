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

function EtherscanIcon({ className }: { className?: string }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      className={className}
    >
      {/* Circle background */}
      <circle cx="7" cy="7" r="6.5" fill="#666666" />
      {/* Swoosh/arc at bottom */}
      <path
        d="M12.5 9.5C11 12 9 13 7 13C4.5 13 2.5 11.5 1.5 9.5"
        stroke="#999999"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
      {/* Three bars (chart) */}
      <rect x="3.5" y="5.5" width="1.5" height="5" rx="0.5" fill="white" />
      <rect x="6.25" y="3.5" width="1.5" height="7" rx="0.5" fill="white" />
      <rect x="9" y="4.5" width="1.5" height="6" rx="0.5" fill="white" />
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
        <span className="font-mono text-gray-900">{address}</span>
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
          <a
            href={etherscanUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="p-1 hover:text-gray-900 transition-colors"
            title="View on Etherscan"
          >
            <EtherscanIcon />
          </a>
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
