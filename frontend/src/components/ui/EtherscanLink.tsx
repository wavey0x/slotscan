'use client';

import { cn } from '@/lib/utils';

interface EtherscanLinkProps {
  href: string;
  className?: string;
  title?: string;
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
      <circle cx="7" cy="7" r="6.5" fill="#666666" />
      <path
        d="M12.5 9.5C11 12 9 13 7 13C4.5 13 2.5 11.5 1.5 9.5"
        stroke="#999999"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
      <rect x="3.5" y="5.5" width="1.5" height="5" rx="0.5" fill="white" />
      <rect x="6.25" y="3.5" width="1.5" height="7" rx="0.5" fill="white" />
      <rect x="9" y="4.5" width="1.5" height="6" rx="0.5" fill="white" />
    </svg>
  );
}

export function EtherscanLink({ href, className, title = 'View on Etherscan' }: EtherscanLinkProps) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn('p-1 hover:text-gray-900 transition-colors', className)}
      title={title}
    >
      <EtherscanIcon />
    </a>
  );
}
