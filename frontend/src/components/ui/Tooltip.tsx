'use client';

/**
 * Tooltip component for displaying additional information on hover.
 *
 * STYLE NOTES:
 * - Do not change cursor styles (e.g., cursor-help, cursor-pointer)
 *   on tooltip triggers. Let the default cursor behavior remain unchanged.
 * - For copyable values (addresses, hashes), use the dotted border hover pattern:
 *   `group inline-flex items-center gap-2 px-2 py-1 rounded-md transition
 *    border border-transparent hover:border-dashed hover:border-gray-400`
 *   This shows a dotted outline on hover to indicate the value is interactive.
 */

import { useState, useRef, useEffect, ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
  className?: string;
  position?: 'top' | 'bottom' | 'left' | 'right';
  delay?: number;
}

export function Tooltip({
  content,
  children,
  className,
  position = 'top',
  delay = 200
}: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const showTooltip = () => {
    timeoutRef.current = setTimeout(() => setIsVisible(true), delay);
  };

  const hideTooltip = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    setIsVisible(false);
  };

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const positionClasses = {
    top: 'bottom-full left-0 mb-2',
    bottom: 'top-full left-0 mt-2',
    left: 'right-full top-0 mr-2',
    right: 'left-full top-0 ml-2',
  };

  return (
    <div
      className="relative inline-block"
      onMouseEnter={showTooltip}
      onMouseLeave={hideTooltip}
    >
      {children}
      {isVisible && content && (
        <div
          ref={tooltipRef}
          className={cn(
            'absolute z-50 px-3 py-2 text-xs bg-gray-900 text-white rounded shadow-lg whitespace-nowrap',
            'animate-in fade-in duration-150',
            positionClasses[position],
            className
          )}
        >
          {content}
        </div>
      )}
    </div>
  );
}
