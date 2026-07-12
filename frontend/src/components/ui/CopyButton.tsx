'use client';

import { useState, useCallback } from 'react';
import { Check, Copy } from 'lucide-react';
import { cn } from '@/lib/utils';

interface CopyButtonProps {
  value: string;
  className?: string;
  size?: 'sm' | 'md';
  label?: string;
}

export function CopyButton({ value, className, size = 'sm', label = 'Copy' }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const iconSize = size === 'md' ? 14 : 12;

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
      aria-label={label}
      className={cn(
        'inline-flex h-5 w-5 shrink-0 items-center justify-center text-gray-400 transition-colors hover:text-gray-900 focus-visible:text-gray-900 focus-visible:outline-none',
        className
      )}
      title={copied ? 'Copied!' : label}
    >
      {copied ? (
        <Check size={iconSize} strokeWidth={1.5} className="text-green" />
      ) : (
        <Copy size={iconSize} strokeWidth={1.25} />
      )}
      <span className="sr-only" role="status" aria-live="polite">
        {copied ? 'Copied' : ''}
      </span>
    </button>
  );
}
