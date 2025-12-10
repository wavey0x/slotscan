'use client';

import Link from 'next/link';
import { CopyButton } from '@/components/ui/CopyButton';
import { EtherscanLink } from '@/components/ui/EtherscanLink';
import { truncateAddress } from '@/lib/utils';
import { getAddressExplorerUrl } from '@/lib/constants';
import { cn } from '@/lib/utils';

export type TabType = 'layout' | 'transaction';

interface ContractNavProps {
  chain: string;
  address: string;
  contractName?: string | null;
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
}

export function ContractNav({
  chain,
  address,
  contractName,
  activeTab,
  onTabChange,
}: ContractNavProps) {
  const abbreviatedAddress = truncateAddress(address);

  const tabs: { label: string; value: TabType }[] = [
    { label: 'Layout', value: 'layout' },
    { label: 'Transaction', value: 'transaction' },
  ];

  return (
    <div className="border-b border-gray-300 mb-6">
      <div className="flex items-center justify-between py-3">
        {/* Contract info */}
        <div className="flex items-center gap-4">
          <Link
            href="/"
            className="text-gray-400 hover:text-gray-600 text-sm no-underline"
          >
            &larr;
          </Link>
          <span className="group inline-flex items-center gap-2">
            <span className="font-mono text-gray-900">
              {contractName ? `${contractName} (${abbreviatedAddress})` : abbreviatedAddress}
            </span>
            <span className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <CopyButton value={address} />
              <EtherscanLink href={getAddressExplorerUrl(chain, address)} />
            </span>
          </span>
        </div>

        {/* Navigation tabs */}
        <nav className="flex items-center gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.value}
              onClick={() => onTabChange(tab.value)}
              className={cn(
                'px-3 py-1.5 text-sm transition-colors',
                activeTab === tab.value
                  ? 'text-gray-900 border-b-2 border-black -mb-[1px]'
                  : 'text-gray-500 hover:text-gray-700'
              )}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>
    </div>
  );
}
