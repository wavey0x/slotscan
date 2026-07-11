'use client';

import { useState } from 'react';
import { CopyButton } from '@/components/ui/CopyButton';
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
  const [showRaw, setShowRaw] = useState(false);

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
      <CopyButton
        value={rawValue}
        label="Copy value"
        className="opacity-0 group-hover:opacity-100 focus:opacity-100"
      />
    </div>
  );
}
