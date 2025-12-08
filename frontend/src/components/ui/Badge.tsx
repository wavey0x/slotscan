import { cn } from '@/lib/utils';
import { ReactNode } from 'react';

interface BadgeProps {
  children: ReactNode;
  variant?: 'default' | 'success' | 'error';
  className?: string;
}

export function Badge({ children, variant = 'default', className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center border px-2 py-0.5 text-xs',
        {
          'bg-gray-100 text-gray-700 border-gray-300': variant === 'default',
          'bg-white text-green border-gray-300': variant === 'success',
          'bg-white text-red border-gray-300': variant === 'error',
        },
        className
      )}
    >
      {children}
    </span>
  );
}
