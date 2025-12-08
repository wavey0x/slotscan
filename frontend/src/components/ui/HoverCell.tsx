'use client';

import { ReactNode } from 'react';
import { cn, isAddress, isTxHash } from '@/lib/utils';
import { CopyButton } from './CopyButton';
import { EtherscanLink } from './EtherscanLink';
import { Tooltip } from './Tooltip';

interface HoverCellProps {
  /** Display value (truncated) */
  display: string;
  /** Full value for copy/tooltip */
  value: string;
  /** Chain ID for etherscan links */
  chainId?: string | number;
  /** Optional tooltip content override */
  tooltip?: ReactNode;
  /** Additional class names */
  className?: string;
  /** Text color class */
  colorClass?: string;
  /** Force actions to be visible even when display === value */
  forceActions?: boolean;
}

function getEtherscanUrl(chainId: string | number, value: string): string | null {
  const chainNum = typeof chainId === 'string' ? parseInt(chainId, 10) : chainId;

  const explorers: Record<number, string> = {
    1: 'https://etherscan.io',
    5: 'https://goerli.etherscan.io',
    11155111: 'https://sepolia.etherscan.io',
    137: 'https://polygonscan.com',
    42161: 'https://arbiscan.io',
    10: 'https://optimistic.etherscan.io',
    8453: 'https://basescan.org',
  };

  const baseUrl = explorers[chainNum];
  if (!baseUrl) return null;

  if (isAddress(value)) {
    return `${baseUrl}/address/${value}`;
  }
  if (isTxHash(value)) {
    return `${baseUrl}/tx/${value}`;
  }
  return null;
}

export function HoverCell({
  display,
  value,
  chainId,
  tooltip,
  className,
  colorClass = 'text-gray-900',
  forceActions = false,
}: HoverCellProps) {
  const etherscanUrl = chainId ? getEtherscanUrl(chainId, value) : null;
  const showActions = forceActions || display !== value || etherscanUrl;

  const tooltipContent = tooltip || (
    <span className="font-mono break-all max-w-xs">{value}</span>
  );

  return (
    <Tooltip content={tooltipContent} position="top" delay={300}>
      <span
        className={cn(
          'group/cell relative inline-block cursor-default',
          className
        )}
      >
        <span className={cn('font-mono truncate', colorClass)}>
          {display}
        </span>
        {showActions && (
          <span className="absolute left-full top-1/2 -translate-y-1/2 ml-0.5 opacity-0 group-hover/cell:opacity-100 flex items-center gap-0.5 bg-white/90 transition-opacity z-10">
            <CopyButton value={value} />
            {etherscanUrl && (
              <EtherscanLink href={etherscanUrl} />
            )}
          </span>
        )}
      </span>
    </Tooltip>
  );
}
