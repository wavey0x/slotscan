'use client';

import { ReactNode } from 'react';
import { cn, isAddress, isTxHash } from '@/lib/utils';
import { CopyButton } from './CopyButton';
import { DetailPopover } from './DetailPopover';

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
  /** Accessible label for the copy action */
  copyLabel?: string;
  /** Wrap long display values instead of truncating them */
  wrap?: boolean;
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
  copyLabel = 'Copy value',
  wrap = false,
}: HoverCellProps) {
  const etherscanUrl = chainId ? getEtherscanUrl(chainId, value) : null;
  const showActions = forceActions || display !== value;

  const tooltipContent = tooltip || (
    <span className="font-mono break-all max-w-xs">{value}</span>
  );

  return (
    <DetailPopover content={tooltipContent} delay={300} className={wrap ? 'min-w-0 max-w-full' : undefined}>
      <span
        className={cn(
          'group/cell inline-flex max-w-full items-center cursor-default',
          className
        )}
      >
        {etherscanUrl ? (
          <a
            href={etherscanUrl}
            target="_blank"
            rel="noopener noreferrer"
            className={cn(
              'inline-block max-w-full align-bottom font-mono hover:underline',
              wrap ? 'whitespace-pre-wrap break-words [overflow-wrap:anywhere]' : 'truncate',
              colorClass,
            )}
          >
            {display}
          </a>
        ) : (
          <span className={cn(
            'inline-block max-w-full align-bottom font-mono',
            wrap ? 'whitespace-pre-wrap break-words [overflow-wrap:anywhere]' : 'truncate',
            colorClass,
          )}>
            {display}
          </span>
        )}
        {showActions && (
          <span className="ml-0.5 flex shrink-0 items-center">
            <CopyButton value={value} label={copyLabel} />
          </span>
        )}
      </span>
    </DetailPopover>
  );
}
