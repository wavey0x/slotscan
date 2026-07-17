import { cn } from '@/lib/utils';

export function ViewSwitch<T extends string>({
  label,
  value,
  options,
  onChange,
  showLabel = true,
  orientation = 'horizontal',
}: {
  label: string;
  value: T;
  options: readonly { value: T; label: string; disabled?: boolean }[];
  onChange: (value: T) => void;
  showLabel?: boolean;
  orientation?: 'horizontal' | 'vertical';
}) {
  return (
    <div className={cn(
      'flex gap-2',
      orientation === 'vertical' ? 'flex-col items-stretch' : 'items-center',
    )}>
      {showLabel && <span className="text-[10px] uppercase tracking-wide text-gray-400">{label}</span>}
      <div
        className={cn(
          'shrink-0 border border-gray-300 bg-white',
          orientation === 'vertical' ? 'flex w-full flex-col' : 'inline-flex h-7',
        )}
        role="group"
        aria-label={label}
        aria-orientation={orientation}
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
              orientation === 'vertical' && 'h-7 border-b border-gray-200 text-left last:border-b-0',
              value === option.value
                ? 'bg-gray-700 text-white'
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
