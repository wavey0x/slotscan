'use client';

import { ReactNode } from 'react';
import { cn, isAddress, isTxHash, shouldShowCopyAction } from '@/lib/utils';
import { CopyButton } from './CopyButton';
import { DetailPopover } from './DetailPopover';

interface HoverCellProps {
  /** Display value (truncated) */
  display: string;
  /** Full value for copy/tooltip */
  value: string;
  /** Semantic value used to decide whether a copy action is useful */
  copyActionValue?: unknown;
  /** Chain ID for etherscan links */
  chainId?: string | number;
  /** Optional tooltip content override */
  tooltip?: ReactNode;
  /** Additional class names */
  className?: string;
  /** Text color class */
  colorClass?: string;
  /** Accessible label for the copy action */
  copyLabel?: string;
  /** Put the copy action in the detail disclosure instead of beside the compact value. */
  copyInDetail?: boolean;
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
  copyActionValue,
  chainId,
  tooltip,
  className,
  colorClass = 'text-gray-900',
  copyLabel = 'Copy value',
  copyInDetail = false,
  wrap = false,
}: HoverCellProps) {
  const explorerValue = copyActionValue === undefined ? value : String(copyActionValue);
  const etherscanUrl = chainId ? getEtherscanUrl(chainId, explorerValue) : null;
  const showActions = shouldShowCopyAction(
    copyActionValue === undefined ? value : copyActionValue,
    display,
  );

  const detailValue = tooltip ?? value;
  const detailText = typeof detailValue === 'string' ? detailValue : null;
  const detailContent = detailText === null ? detailValue : (
    <span className="block max-w-xs whitespace-normal break-all font-mono [overflow-wrap:anywhere]">
      {detailText}
    </span>
  );
  const hasSupplementalDetail = Boolean(detailValue) && (
    (copyInDetail && showActions)
    || detailText === null
    || detailText !== display
  );
  const tooltipContent = copyInDetail && showActions ? (
    <div className="flex max-w-xs items-start gap-1">
      <div className="min-w-0">{detailContent}</div>
      <CopyButton value={value} label={copyLabel} className="-my-1 shrink-0" />
    </div>
  ) : detailContent;

  const cell = (
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
            'inline-block max-w-full align-bottom font-mono',
            'hover:underline',
            wrap ? 'whitespace-pre-wrap break-words [overflow-wrap:anywhere]' : 'truncate',
            colorClass,
          )}>
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
      {showActions && !copyInDetail && (
        <span className="ml-0.5 flex shrink-0 items-center">
          <CopyButton value={value} label={copyLabel} />
        </span>
      )}
    </span>
  );

  if (!hasSupplementalDetail) return cell;

  return (
    <DetailPopover content={tooltipContent} delay={300} className="min-w-0 max-w-full">
      {cell}
    </DetailPopover>
  );
}
