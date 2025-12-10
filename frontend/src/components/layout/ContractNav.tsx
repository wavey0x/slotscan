'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { CopyButton } from '@/components/ui/CopyButton';
import { EtherscanLink } from '@/components/ui/EtherscanLink';
import { truncateAddress } from '@/lib/utils';
import { getAddressExplorerUrl } from '@/lib/constants';
import { cn } from '@/lib/utils';

interface ContractNavProps {
  chain: string;
  address: string;
  contractName?: string | null;
}

export function ContractNav({ chain, address, contractName }: ContractNavProps) {
  const pathname = usePathname();
  const abbreviatedAddress = truncateAddress(address);

  const isLayoutPage = pathname.endsWith('/layout');
  const basePath = `/${chain}/${address}`;

  const tabs = [
    { label: 'Transactions', href: basePath, active: !isLayoutPage },
    { label: 'Layout', href: `${basePath}/layout`, active: isLayoutPage },
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
            <Link
              key={tab.href}
              href={tab.href}
              className={cn(
                'px-3 py-1.5 text-sm no-underline transition-colors',
                tab.active
                  ? 'text-gray-900 border-b-2 border-black -mb-[1px]'
                  : 'text-gray-500 hover:text-gray-700'
              )}
            >
              {tab.label}
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );
}
