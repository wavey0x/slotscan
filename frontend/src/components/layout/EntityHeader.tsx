import { ReactNode } from 'react';

interface EntityHeaderProps {
  title: string;
  identifier: ReactNode;
  status?: ReactNode;
  meta?: ReactNode;
}

export function EntityHeader({ title, identifier, status, meta }: EntityHeaderProps) {
  return (
    <header className="mb-6 border-b border-gray-300 pb-4">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div className="min-w-0">
          <h1 className="truncate text-lg font-medium text-gray-900">{title}</h1>
          <div className="mt-1 flex min-w-0 items-center text-xs text-gray-500">
            {identifier}
          </div>
        </div>
        {status && (
          <div className="shrink-0 text-[10px] uppercase tracking-wide text-gray-500">
            {status}
          </div>
        )}
      </div>
      {meta && <div className="mt-2 text-[10px] text-gray-500">{meta}</div>}
    </header>
  );
}
