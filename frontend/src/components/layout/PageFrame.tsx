import { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface PageFrameProps {
  children: ReactNode;
  variant?: 'form' | 'data';
  className?: string;
}

export function PageFrame({ children, variant = 'data', className }: PageFrameProps) {
  return (
    <div
      className={cn(
        'mx-auto w-full px-4 py-6 sm:px-6 lg:px-8',
        variant === 'form' ? 'max-w-2xl' : 'max-w-[90rem]',
        className
      )}
    >
      {children}
    </div>
  );
}
