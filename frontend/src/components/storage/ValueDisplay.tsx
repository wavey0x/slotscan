'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';

interface ValueDisplayProps {
  value: string;
  rawValue: string;
  typeLabel?: string | null;
  className?: string;
}

export function ValueDisplay({
  value,
  rawValue,
  className,
}: ValueDisplayProps) {
  const [copied, setCopied] = useState(false);
  const [showRaw, setShowRaw] = useState(false);

  const copyValue = async () => {
    await navigator.clipboard.writeText(rawValue);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const displayValue = showRaw ? rawValue : value;

  return (
    <div className={cn('flex items-center gap-2 group', className)}>
      <button
        onClick={() => setShowRaw(!showRaw)}
        className="text-sm text-right max-w-xs truncate text-gray-900 hover:underline"
        title={rawValue}
      >
        {displayValue}
      </button>
      <button
        onClick={copyValue}
        className="opacity-0 group-hover:opacity-100 text-xs text-gray-500 hover:text-gray-900"
      >
        {copied ? 'copied' : 'copy'}
      </button>
    </div>
  );
}
