import { cn } from '@/lib/utils';

export function ViewSwitch<T extends string>({
  label,
  value,
  options,
  onChange,
  showLabel = true,
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string; disabled?: boolean }[];
  onChange: (value: T) => void;
  showLabel?: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      {showLabel && <span className="text-[10px] uppercase tracking-wide text-gray-400">{label}</span>}
      <div
        className="inline-flex h-7 shrink-0 border border-gray-300 bg-white"
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
              'px-2.5 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-40',
              value === option.value
                ? 'bg-gray-900 text-white'
                : 'text-gray-500 hover:text-gray-900',
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
