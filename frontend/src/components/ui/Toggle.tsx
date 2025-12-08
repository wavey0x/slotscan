import { cn } from '@/lib/utils';

interface ToggleProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  className?: string;
}

/**
 * Minimalist toggle switch following style guide.
 * Sharp edges, black/white, no fancy animations.
 */
export function Toggle({ label, checked, onChange, className }: ToggleProps) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={cn(
        'inline-flex items-center gap-2 text-xs',
        className
      )}
    >
      <span className="text-gray-500">{label}</span>
      <span
        className={cn(
          'relative w-8 h-4 border transition-colors',
          checked
            ? 'bg-black border-black'
            : 'bg-white border-gray-300'
        )}
      >
        <span
          className={cn(
            'absolute top-0.5 w-2.5 h-2.5 transition-all',
            checked
              ? 'left-[18px] bg-white'
              : 'left-0.5 bg-gray-400'
          )}
        />
      </span>
    </button>
  );
}
