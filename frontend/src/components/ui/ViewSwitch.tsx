import { cn } from '@/lib/utils';

export function ViewSwitch<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string; disabled?: boolean }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-wide text-gray-400">{label}</span>
      <div className="inline-flex border border-gray-300" role="group" aria-label={label}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={value === option.value}
            disabled={option.disabled}
            onClick={() => onChange(option.value)}
            className={cn(
              'px-2 py-1 text-[10px] disabled:cursor-not-allowed disabled:opacity-40',
              value === option.value ? 'bg-gray-900 text-white' : 'text-gray-600 hover:text-gray-900',
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
