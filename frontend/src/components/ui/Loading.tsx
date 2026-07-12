import { cn } from '@/lib/utils';

interface LoadingProps {
  message?: string;
  messages?: string[];
  interval?: number;
  className?: string;
  subtitle?: string;
}

export function Loading({
  message,
  messages,
  className,
  subtitle
}: LoadingProps) {
  const displayMessage = message || messages?.[0] || 'Loading';

  return (
    <div className={cn('flex items-center justify-center py-12', className)}>
      <div className="text-center">
        <div
          className="w-5 h-5 border-2 border-dotted border-gray-400 rounded-full animate-spin mx-auto mb-3"
        />
        <div className="text-gray-500 text-sm" role="status" aria-live="polite">
          {displayMessage}
        </div>
        {subtitle && (
          <div className="text-gray-400 text-xs mt-2">
            {subtitle}
          </div>
        )}
      </div>
    </div>
  );
}
