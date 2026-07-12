export function DataQuality({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;

  return (
    <details className="mb-5 border-y border-gray-300 py-2 text-xs text-gray-600">
      <summary className="cursor-pointer text-gray-700">
        Data quality · {warnings.length} {warnings.length === 1 ? 'notice' : 'notices'}
      </summary>
      <ul className="mt-2 space-y-1 pl-4 text-[10px] text-gray-500">
        {warnings.map((warning) => <li key={warning}>{warning}</li>)}
      </ul>
    </details>
  );
}
