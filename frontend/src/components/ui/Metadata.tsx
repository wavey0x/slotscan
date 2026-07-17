import { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export function MetadataItem({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] uppercase tracking-wide text-gray-500">{label}</dt>
      <dd className="mt-0.5 min-w-0 text-xs font-mono text-gray-900">{children}</dd>
    </div>
  );
}

interface Metric {
  label: string;
  value: ReactNode;
  testId?: string;
}

export function MetricList({ metrics, className }: { metrics: Metric[]; className?: string }) {
  return (
    <dl className={cn('flex flex-wrap items-center gap-x-7 gap-y-1', className)}>
      {metrics.map((metric, index) => (
        <div key={`${metric.label}:${index}`} data-testid={metric.testId} className="flex items-baseline gap-1.5">
          <dt className="text-[10px] uppercase tracking-wide text-gray-500">{metric.label}</dt>
          <dd className="text-sm text-gray-700">{metric.value}</dd>
        </div>
      ))}
    </dl>
  );
}
