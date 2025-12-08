'use client';

/**
 * HoverCard component for displaying detailed information on hover.
 *
 * Goals for UX:
 * - Always render in the viewport (portal to body, fixed positioning)
 * - Position locks when card appears (no jittery following)
 * - User can move cursor into card to select text / interact
 * - Repositions only on scroll/resize (edge cases)
 */

import { useState, useRef, useEffect, useLayoutEffect, ReactNode, useCallback } from 'react';
import { createPortal } from 'react-dom';
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
  position = 'top',
  delay = 80,
  maxWidth = 'max-w-md',
}: HoverCardProps) {
  const [isVisible, setIsVisible] = useState(false);
  const [coords, setCoords] = useState({ top: 0, left: 0 });
  const [cardSize, setCardSize] = useState<{ width: number; height: number }>({ width: 260, height: 180 });
  const [mounted, setMounted] = useState(false);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const triggerRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  // Stores cursor position at moment of hover start (locked position)
  const anchorRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });

  // Ensure we only render portal on client
  useEffect(() => {
    setMounted(true);
  }, []);

  const calculatePosition = useCallback(
    (size?: { width: number; height: number }) => {
      const offset = 12;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const { x, y } = anchorRef.current;

      const width = size?.width ?? cardSize.width;
      const height = size?.height ?? cardSize.height;

      // Prefer top-right of cursor; if not enough vertical room, place below
      const fitsAbove = y - height - offset > 8;
      let top = fitsAbove ? y - height - offset : y + offset;
      let left = x + offset;

      // Clamp horizontally
      if (left + width + 8 > vw) {
        left = Math.max(8, vw - width - 8);
      }
      if (left < 8) left = 8;

      // Clamp vertically
      if (top + height + 8 > vh) {
        top = Math.max(8, vh - height - 8);
      }
      if (top < 8) top = 8;

      setCoords({ top, left });
    },
    [cardSize]
  );

  const showCard = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    // Calculate position once based on locked anchor point
    calculatePosition();
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

  // Recalculate position on scroll/resize while visible (keeps card in viewport)
  useEffect(() => {
    if (!isVisible) return;

    const handleScrollOrResize = () => calculatePosition();
    window.addEventListener('scroll', handleScrollOrResize, true);
    window.addEventListener('resize', handleScrollOrResize);

    return () => {
      window.removeEventListener('scroll', handleScrollOrResize, true);
      window.removeEventListener('resize', handleScrollOrResize);
    };
  }, [isVisible, calculatePosition]);

  // Measure card size after it renders to refine positioning
  useLayoutEffect(() => {
    if (isVisible && cardRef.current) {
      const rect = cardRef.current.getBoundingClientRect();
      const nextSize = { width: rect.width, height: rect.height };
      if (nextSize.width !== cardSize.width || nextSize.height !== cardSize.height) {
        setCardSize(nextSize);
        // Recalculate using measured size
        calculatePosition(nextSize);
      }
    }
  }, [isVisible, content, cardSize.width, cardSize.height, calculatePosition]);

  const cardContent = isVisible && content && mounted ? (
    createPortal(
      <div
        ref={cardRef}
        className="fixed pointer-events-auto"
        style={{
          top: coords.top,
          left: coords.left,
          zIndex: 99999,
        }}
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
      </div>,
      document.body
    )
  ) : null;

  return (
    <>
      <div
        ref={triggerRef}
        className={cn('inline-block', className)}
        onMouseEnter={(e) => {
          // Lock anchor position at hover start
          anchorRef.current = { x: e.clientX, y: e.clientY };
          showCard();
        }}
        onMouseLeave={hideCard}
      >
        {children}
      </div>
      {cardContent}
    </>
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

/**
 * Row component for key-value display in hover cards
 */
export function HoverCardRow({
  label,
  value,
  labelClassName,
  valueClassName,
}: {
  label: string;
  value: ReactNode;
  labelClassName?: string;
  valueClassName?: string;
}) {
  return (
    <div className="flex items-start gap-2 text-xs">
      <span className={cn('text-gray-400 flex-shrink-0', labelClassName)}>
        {label}
      </span>
      <span className={cn('text-gray-200 font-mono break-all', valueClassName)}>
        {value}
      </span>
    </div>
  );
}
