import Link from 'next/link';

interface BackLinkProps {
  href: string;
  label?: string;
}

export function BackLink({ href, label = 'Back' }: BackLinkProps) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-900 mb-6 no-underline hover:no-underline"
    >
      <span aria-hidden="true">&larr;</span>
      {label}
    </Link>
  );
}
