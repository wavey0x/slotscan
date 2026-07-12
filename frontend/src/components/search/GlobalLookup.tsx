'use client';

import { FormEvent, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { inspectionPath } from '@/lib/navigation';
import { saveRecentInspection } from '@/lib/utils';

export function GlobalLookup() {
  const pathname = usePathname();
  const router = useRouter();
  const [value, setValue] = useState('');
  const [invalid, setInvalid] = useState(false);

  if (pathname === '/') return null;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const destination = inspectionPath(value);
    if (!destination) {
      setInvalid(true);
      return;
    }
    const normalized = value.trim();
    saveRecentInspection({
      chain: '1',
      kind: normalized.length === 66 ? 'transaction' : 'contract',
      value: normalized,
    });
    setValue('');
    setInvalid(false);
    router.push(destination);
  };

  return (
    <>
      <form onSubmit={submit} className="hidden w-full max-w-sm items-center sm:flex">
        <label htmlFor="global-lookup" className="sr-only">Contract address or transaction hash</label>
        <input
          id="global-lookup"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            setInvalid(false);
          }}
          aria-invalid={invalid}
          title={invalid ? 'Enter a contract address or transaction hash' : undefined}
          placeholder="Address or transaction hash"
          className="h-8 min-w-0 flex-1 border border-gray-300 bg-white px-2 text-xs placeholder:text-gray-500 focus:border-black focus:outline-none"
        />
        <button type="submit" className="h-8 border-y border-r border-gray-300 px-3 text-xs text-gray-700 hover:bg-gray-100">
          Search
        </button>
      </form>
      <Link href="/" className="text-xs text-gray-500 sm:hidden">Search</Link>
    </>
  );
}
