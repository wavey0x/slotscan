'use client';

import { CopyButton } from '@/components/ui/CopyButton';
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
      {/* Contract info - centered */}
      <div className="flex items-center justify-center py-3">
        <span className="group inline-flex items-center gap-2">
          <a
            href={getAddressExplorerUrl(chain, address)}
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono text-gray-900 hover:underline"
          >
            {contractName ? `${contractName} (${abbreviatedAddress})` : abbreviatedAddress}
          </a>
          <span className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <CopyButton value={address} />
          </span>
        </span>
      </div>

      {/* Navigation tabs - centered */}
      <nav className="flex items-center justify-center gap-6 -mb-[1px]">
        {tabs.map((tab) => (
          <button
            key={tab.value}
            onClick={() => onTabChange(tab.value)}
            className={cn(
              'px-3 py-2 text-sm transition-colors',
              activeTab === tab.value
                ? 'text-gray-900 border-b-2 border-black'
                : 'text-gray-500 hover:text-gray-700'
            )}
          >
            {tab.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
