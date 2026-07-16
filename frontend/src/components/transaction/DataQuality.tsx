export function DataQuality({
  warnings,
  action,
}: {
  warnings: string[];
  action?: {
    label: string;
    onClick: () => void;
    disabled?: boolean;
  };
}) {
  if (warnings.length === 0) return null;

  return (
    <div className="mb-5 flex items-start gap-3 border-y border-gray-300 py-2 text-xs text-gray-600">
      <details className="min-w-0 flex-1">
        <summary className="cursor-pointer text-gray-700">
          Data quality · {warnings.length} {warnings.length === 1 ? 'notice' : 'notices'}
        </summary>
        <ul className="mt-2 space-y-1 pl-4 text-[10px] text-gray-500">
          {warnings.map((warning) => <li key={warning}>{warning}</li>)}
        </ul>
      </details>
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          disabled={action.disabled}
          className="shrink-0 border border-gray-300 px-2 py-1 text-[10px] text-gray-700 hover:border-gray-500 disabled:cursor-wait disabled:text-gray-400"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
