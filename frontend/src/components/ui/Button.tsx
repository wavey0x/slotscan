import { cn } from '@/lib/utils';
import { ButtonHTMLAttributes, forwardRef } from 'react';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'sm' | 'md';
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          'inline-flex items-center justify-center border text-sm transition-colors',
          'disabled:pointer-events-none disabled:opacity-50',
          {
            'bg-black text-white border-black hover:bg-gray-900': variant === 'primary',
            'bg-white text-gray-900 border-gray-300 hover:bg-gray-100': variant === 'secondary',
            'bg-transparent text-gray-700 border-transparent hover:bg-gray-100': variant === 'ghost',
          },
          {
            'h-8 px-3': size === 'sm',
            'h-9 px-4': size === 'md',
          },
          className
        )}
        {...props}
      />
    );
  }
);

Button.displayName = 'Button';
