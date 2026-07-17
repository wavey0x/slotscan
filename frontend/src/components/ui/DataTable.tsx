'use client';

import { CSSProperties, ReactNode, useCallback, useLayoutEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils';

export const dataTableHeadCellClass = 'sticky top-0 z-10 bg-white px-2 py-1.5 text-left text-[10px] font-medium uppercase tracking-wide text-gray-400 shadow-[inset_0_-1px_0_rgb(var(--color-gray-300))]';
export const dataTableCellClass = 'px-2 py-1.5 align-top';

interface ScrollState {
  overflowing: boolean;
  atStart: boolean;
  atEnd: boolean;
}

/**
 * Horizontal scrolling only engages when the table is wider than the
 * viewport; otherwise the wrapper stays overflow-visible so the sticky
 * column headers can pin to the viewport. Edge fades signal hidden columns.
 */
export function DataTable({
  children,
  minWidth = '44rem',
  className,
}: {
  children: ReactNode;
  minWidth?: string;
  className?: string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [{ overflowing, atStart, atEnd }, setScrollState] = useState<ScrollState>({
    overflowing: false,
    atStart: true,
    atEnd: true,
  });

  const updateScrollState = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const next: ScrollState = {
      overflowing: el.scrollWidth > el.clientWidth + 1,
      atStart: el.scrollLeft <= 1,
      atEnd: el.scrollLeft + el.clientWidth >= el.scrollWidth - 1,
    };
    setScrollState((current) => (
      current.overflowing === next.overflowing
        && current.atStart === next.atStart
        && current.atEnd === next.atEnd
        ? current
        : next
    ));
  }, []);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    updateScrollState();
    const observer = new ResizeObserver(updateScrollState);
    observer.observe(el);
    if (el.firstElementChild) observer.observe(el.firstElementChild);
    el.addEventListener('scroll', updateScrollState, { passive: true });
    return () => {
      observer.disconnect();
      el.removeEventListener('scroll', updateScrollState);
    };
  }, [updateScrollState]);

  return (
    <div className="relative w-full min-w-0 max-w-full">
      <div
        ref={scrollRef}
        className={cn(
          'w-full min-w-0 max-w-full',
          overflowing ? 'overflow-x-auto' : 'overflow-x-visible',
        )}
        data-testid="data-table-scroll"
      >
        <table
          className={cn('w-full table-fixed border-collapse sm:min-w-[var(--table-min-width)]', className)}
          style={{ '--table-min-width': minWidth } as CSSProperties}
        >
          {children}
        </table>
      </div>
      {overflowing && !atStart && (
        <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-0 w-5 bg-gradient-to-r from-white to-transparent" />
      )}
      {overflowing && !atEnd && (
        <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 right-0 w-5 bg-gradient-to-l from-white to-transparent" />
      )}
    </div>
  );
}
