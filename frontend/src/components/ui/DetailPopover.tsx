'use client';

import {
  ReactNode,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { cn } from '@/lib/utils';

interface DetailPopoverProps {
  content: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  dialogLabel?: string;
  delay?: number;
  maxWidth?: string;
}

/**
 * One disclosure primitive for compact forensic detail. It is available by
 * hover, focus, and click/touch and always renders inside the viewport.
 */
export function DetailPopover({
  content,
  children,
  className,
  contentClassName,
  dialogLabel,
  delay = 100,
  maxWidth = 'max-w-sm',
}: DetailPopoverProps) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [coords, setCoords] = useState({ top: 8, left: 8 });
  const triggerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const openTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pointerRef = useRef<{ x: number; y: number } | null>(null);
  const suppressFocusOpenRef = useRef(false);
  const panelId = useId();

  useEffect(() => setMounted(true), []);

  const clearTimers = useCallback(() => {
    if (openTimer.current) clearTimeout(openTimer.current);
    if (closeTimer.current) clearTimeout(closeTimer.current);
  }, []);

  const positionPanel = useCallback(() => {
    const trigger = triggerRef.current?.getBoundingClientRect();
    const panel = panelRef.current?.getBoundingClientRect();
    if (!trigger) return;

    const anchorX = pointerRef.current?.x ?? trigger.left;
    const anchorY = pointerRef.current?.y ?? trigger.top;
    const width = panel?.width ?? 320;
    const height = panel?.height ?? 160;
    const gap = 8;
    const margin = 8;
    const above = anchorY - height - gap >= margin;
    const top = above ? anchorY - height - gap : Math.min(anchorY + gap, window.innerHeight - height - margin);
    const left = Math.min(Math.max(anchorX, margin), window.innerWidth - width - margin);
    const next = { top: Math.max(margin, top), left: Math.max(margin, left) };
    setCoords((current) => (
      current.top === next.top && current.left === next.left ? current : next
    ));
  }, []);

  const scheduleOpen = (delayMs = delay) => {
    clearTimers();
    openTimer.current = setTimeout(() => setOpen(true), delayMs);
  };

  const scheduleClose = () => {
    clearTimers();
    closeTimer.current = setTimeout(() => setOpen(false), 100);
  };

  useLayoutEffect(() => {
    if (open) positionPanel();
  }, [open, positionPanel]);

  useEffect(() => {
    if (!open) return;
    const reposition = () => positionPanel();
    const closeOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !panelRef.current?.contains(target)) {
        setOpen(false);
      }
    };
    window.addEventListener('scroll', reposition, true);
    window.addEventListener('resize', reposition);
    document.addEventListener('pointerdown', closeOnOutsidePointer);
    return () => {
      window.removeEventListener('scroll', reposition, true);
      window.removeEventListener('resize', reposition);
      document.removeEventListener('pointerdown', closeOnOutsidePointer);
    };
  }, [open, positionPanel]);

  useEffect(() => () => clearTimers(), [clearTimers]);

  const closeForFocus = (event: React.FocusEvent) => {
    const next = event.relatedTarget as Node | null;
    if (next && (triggerRef.current?.contains(next) || panelRef.current?.contains(next))) return;
    scheduleClose();
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== 'Escape') return;
    clearTimers();
    setOpen(false);
    const trigger = triggerRef.current;
    if (trigger && document.activeElement !== trigger) {
      suppressFocusOpenRef.current = true;
      trigger.focus();
    }
  };

  const panel = open && mounted && content ? createPortal(
    <div
      ref={panelRef}
      id={panelId}
      role="dialog"
      aria-label={dialogLabel}
      data-testid="detail-popover"
      className={cn(
        'fixed z-[99999] rounded-[8px] border border-gray-200 bg-white px-[10px] py-[8px] text-xs text-gray-700',
        'shadow-[0_6px_18px_rgb(0_0_0/0.08),0_1px_2px_rgb(0_0_0/0.06)]',
        maxWidth,
        contentClassName,
      )}
      style={{ top: coords.top, left: coords.left }}
      onMouseEnter={clearTimers}
      onMouseLeave={scheduleClose}
      onFocus={clearTimers}
      onBlur={closeForFocus}
      onKeyDown={handleKeyDown}
    >
      {content}
    </div>,
    document.body,
  ) : null;

  return (
    <>
      <div
        ref={triggerRef}
        tabIndex={0}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        className={cn('inline-block focus-visible:outline focus-visible:outline-1 focus-visible:outline-gray-500', className)}
        onMouseEnter={(event) => {
          pointerRef.current = { x: event.clientX, y: event.clientY };
          scheduleOpen();
        }}
        onMouseLeave={scheduleClose}
        onFocus={(event) => {
          if (event.target !== event.currentTarget) return;
          if (suppressFocusOpenRef.current) {
            suppressFocusOpenRef.current = false;
            return;
          }
          pointerRef.current = null;
          scheduleOpen(0);
        }}
        onBlur={closeForFocus}
        onPointerDown={clearTimers}
        onClick={(event) => {
          const target = event.target as HTMLElement;
          if (target.closest('a, button, input, select, textarea')) return;
          pointerRef.current = null;
          clearTimers();
          setOpen((visible) => !visible);
        }}
        onKeyDown={handleKeyDown}
      >
        {children}
      </div>
      {panel}
    </>
  );
}

export function DetailSection({
  title,
  children,
  className,
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('space-y-0.5', className)}>
      {title && <div className="text-[10px] font-medium uppercase tracking-wide text-gray-500">{title}</div>}
      {children}
    </div>
  );
}

export function DetailDivider() {
  return <div className="my-1.5 border-t border-gray-200" />;
}
