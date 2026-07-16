import { cn } from '@/lib/utils';

export function ViewSwitch<T extends string>({
  label,
  value,
  options,
  onChange,
  showLabel = true,
  variant = 'segment',
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string; disabled?: boolean }[];
  onChange: (value: T) => void;
  showLabel?: boolean;
  variant?: 'segment' | 'tabs';
}) {
  return (
    <div className="flex items-center gap-2">
      {showLabel && <span className="text-[10px] uppercase tracking-wide text-gray-400">{label}</span>}
      <div
        className={cn(
          'inline-flex h-8',
          variant === 'segment' && 'border border-gray-300 bg-gray-50 p-0.5',
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
              'px-2 text-[10px] disabled:cursor-not-allowed disabled:opacity-40',
              variant === 'tabs'
                ? 'border-b-2'
                : 'transition-colors',
              value === option.value
                ? variant === 'tabs'
                  ? 'border-gray-900 text-gray-900'
                  : 'bg-gray-900 text-white'
                : variant === 'tabs'
                  ? 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-900'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900',
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
