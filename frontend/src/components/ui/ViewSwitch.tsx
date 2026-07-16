import { cn } from '@/lib/utils';

export function ViewSwitch<T extends string>({
  label,
  value,
  options,
  onChange,
  showLabel = true,
  fullWidth = false,
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string; disabled?: boolean }[];
  onChange: (value: T) => void;
  showLabel?: boolean;
  fullWidth?: boolean;
}) {
  return (
    <div className={cn('flex items-center gap-2', fullWidth && 'w-full')}>
      {showLabel && <span className="text-[10px] uppercase tracking-wide text-gray-400">{label}</span>}
      <div
        className={cn(
          'inline-flex h-6 border border-gray-300 bg-gray-50',
          fullWidth && 'w-full shrink-0',
        )}
        role="group"
        aria-label={label}
      >
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={value === option.value}
            disabled={option.disabled}
            onClick={() => onChange(option.value)}
            className={cn(
              'px-2 text-[9px] transition-colors disabled:cursor-not-allowed disabled:opacity-40',
              fullWidth && 'flex-1',
              value === option.value
                ? 'bg-gray-200 text-gray-900'
                : 'text-gray-500 hover:bg-gray-100 hover:text-gray-900',
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
