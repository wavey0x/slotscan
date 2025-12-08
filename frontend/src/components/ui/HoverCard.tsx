'use client';

/**
 * HoverCard component for displaying detailed information on hover.
 *
 * Unlike Tooltip, this provides a larger, more customizable display area
 * that stays visible while the user hovers over the card itself.
 */

import { useState, useRef, useEffect, ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface HoverCardProps {
  content: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  position?: 'top' | 'bottom' | 'left' | 'right';
  delay?: number;
  maxWidth?: string;
}

export function HoverCard({
  content,
  children,
  className,
  contentClassName,
  position = 'bottom',
  delay = 150,
  maxWidth = 'max-w-md',
}: HoverCardProps) {
  const [isVisible, setIsVisible] = useState(false);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const showCard = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = setTimeout(() => setIsVisible(true), delay);
  };

  const hideCard = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    // Small delay before hiding to allow moving to the card
    timeoutRef.current = setTimeout(() => setIsVisible(false), 100);
  };

  const keepVisible = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
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
      ref={containerRef}
      className={cn('relative inline-block', className)}
      onMouseEnter={showCard}
      onMouseLeave={hideCard}
    >
      {children}
      {isVisible && content && (
        <div
          className={cn(
            'absolute z-50',
            positionClasses[position],
          )}
          onMouseEnter={keepVisible}
          onMouseLeave={hideCard}
        >
          <div
            className={cn(
              'bg-gray-900 text-white rounded-lg shadow-xl',
              'border border-gray-700',
              'animate-in fade-in slide-in-from-top-1 duration-150',
              maxWidth,
              contentClassName,
            )}
          >
            {/* Card content */}
            <div className="p-3">
              {content}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Pre-styled sections for consistent card content layout
 */
export function HoverCardSection({
  title,
  children,
  className,
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('space-y-1', className)}>
      {title && (
        <div className="text-[10px] uppercase tracking-wide text-gray-400 font-medium">
          {title}
        </div>
      )}
      {children}
    </div>
  );
}

export function HoverCardDivider() {
  return <div className="border-t border-gray-700 my-2" />;
}
