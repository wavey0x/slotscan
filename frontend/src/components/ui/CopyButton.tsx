'use client';

import { useState, useCallback } from 'react';
import { cn } from '@/lib/utils';

interface CopyButtonProps {
  value: string;
  className?: string;
  size?: 'sm' | 'md';
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

export function CopyButton({ value, className, size = 'sm' }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = value;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [value]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={cn(
        'p-1 text-gray-400 hover:text-gray-900 transition-colors',
        className
      )}
      title={copied ? 'Copied!' : 'Copy'}
    >
      {copied ? (
        <CheckIcon className="text-green" />
      ) : (
        <CopyIcon />
      )}
    </button>
  );
}
