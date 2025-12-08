'use client';

import { useState, useEffect } from 'react';
import { cn } from '@/lib/utils';

interface LoadingProps {
  message?: string;
  messages?: string[];
  interval?: number;
  className?: string;
}

const defaultMessages = [
  'Loading traces',
  'Parsing opcodes',
  'Locating SSTOREs',
  'Decoding storage slots',
  'Resolving variable names',
  'Matching mapping keys',
  'Unpacking structs',
  'Computing keccak256 hashes',
];

export function Loading({
  message,
  messages = defaultMessages,
  interval = 600,
  className
}: LoadingProps) {
  const [messageIndex, setMessageIndex] = useState(0);

  useEffect(() => {
    if (message) return; // Don't rotate if static message provided

    const timer = setInterval(() => {
      setMessageIndex(prev => (prev + 1) % messages.length);
    }, interval);

    return () => clearInterval(timer);
  }, [message, messages.length, interval]);

  const displayMessage = message || messages[messageIndex];

  return (
    <div className={cn('flex items-center justify-center py-12', className)}>
      <div className="text-center">
        <div
          className="w-5 h-5 border-2 border-dotted border-gray-400 rounded-full animate-spin mx-auto mb-3"
        />
        <div className="text-gray-500 text-sm transition-opacity duration-150">
          {displayMessage}
        </div>
      </div>
    </div>
  );
}
