'use client';

import { CopyButton } from '@/components/ui/CopyButton';
import { DetailPopover } from '@/components/ui/DetailPopover';
import { getAddressExplorerUrl } from '@/lib/constants';
import { isAddress, truncateAddress, truncateHash } from '@/lib/utils';

interface PathSegment {
  name: string;
  keys: string[];
}

interface KeyedVariablePathProps {
  path: string;
  typeLabel?: string | null;
  chainId: string;
  /** Keep a single leaf field in canonical order while truncating only its base name. */
  canonicalLeaf?: boolean;
}

function canonicalPath(path: string): string {
  return path.replace(/\s+\([^)]+\)\s*$/, '').trim();
}

function splitPath(path: string): string[] {
  const segments: string[] = [];
  let start = 0;
  let bracketDepth = 0;

  for (let index = 0; index < path.length; index += 1) {
    const character = path[index];
    if (character === '[') bracketDepth += 1;
    if (character === ']') bracketDepth = Math.max(0, bracketDepth - 1);
    if (character === '.' && bracketDepth === 0) {
      segments.push(path.slice(start, index));
      start = index + 1;
    }
  }

  segments.push(path.slice(start));
  return segments.filter(Boolean);
}

function parseSegment(segment: string): PathSegment {
  const firstBracket = segment.indexOf('[');
  if (firstBracket === -1) return { name: segment, keys: [] };

  const keys: string[] = [];
  let cursor = firstBracket;
  while (cursor < segment.length) {
    const open = segment.indexOf('[', cursor);
    if (open === -1) break;

    let depth = 1;
    let close = open + 1;
    while (close < segment.length && depth > 0) {
      if (segment[close] === '[') depth += 1;
      if (segment[close] === ']') depth -= 1;
      close += 1;
    }

    if (depth !== 0) return { name: segment, keys: [] };
    keys.push(segment.slice(open + 1, close - 1));
    cursor = close;
  }

  return { name: segment.slice(0, firstBracket), keys };
}

function abbreviateKey(key: string): string {
  if (isAddress(key)) return truncateAddress(key);
  if (key.length > 20) return truncateHash(key, 6);
  return key;
}

function Key({ value, chainId }: { value: string; chainId: string }) {
  return (
    <span className="whitespace-nowrap">
      [
      {isAddress(value) ? (
        <a
          href={getAddressExplorerUrl(chainId, value)}
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-gray-700 hover:underline"
          title={value}
        >
          {abbreviateKey(value)}
        </a>
      ) : (
        <span title={value}>{abbreviateKey(value)}</span>
      )}
      ]
    </span>
  );
}

function InlineSegment({ segment, chainId }: { segment: PathSegment; chainId: string }) {
  return (
    <span className="whitespace-nowrap">
      <span>{segment.name}</span>
      {segment.keys.map((key, index) => (
        <Key key={`${key}:${index}`} value={key} chainId={chainId} />
      ))}
    </span>
  );
}

interface PathLine {
  name: string | null;
  key: string | null;
  separator: boolean;
}

function segmentLines(segment: PathSegment, separator: boolean): PathLine[] {
  if (segment.keys.length === 0) {
    return [{ name: segment.name, key: null, separator }];
  }

  return segment.keys.map((key, index) => ({
    name: index === 0 ? segment.name : null,
    key,
    separator: separator && index === 0,
  }));
}

export function KeyedVariablePath({
  path,
  typeLabel,
  chainId,
  canonicalLeaf = false,
}: KeyedVariablePathProps) {
  const fullPath = canonicalPath(path);
  const segments = splitPath(fullPath).map(parseSegment);
  const finalSegment = segments.at(-1) ?? { name: fullPath, keys: [] };
  const hasLeafField = finalSegment.keys.length === 0 && segments.length > 1;
  const context = segments.slice(0, -1);
  const keyCount = segments.reduce((count, segment) => count + segment.keys.length, 0);
  const stackKeys = keyCount > 1;
  const canonicalBase = canonicalLeaf && hasLeafField && context.length === 1 && keyCount <= 1
    ? context[0]
    : null;
  const stackedLines = stackKeys
    ? [
        ...context.flatMap((segment, index) => segmentLines(segment, index > 0)),
        ...(!hasLeafField
          ? finalSegment.keys.map((key) => ({ name: null, key, separator: false }))
          : []),
      ]
    : [];

  if (canonicalBase) {
    return (
      <div className="min-w-0 font-mono leading-tight" data-testid="keyed-variable-path">
        <DetailPopover
          className="max-w-full"
          content={(
            <div className="flex max-w-xs items-start gap-1">
              <span className="break-all font-mono text-xs">{fullPath}</span>
              <CopyButton value={fullPath} label="Copy full path" className="-my-1 shrink-0" />
            </div>
          )}
        >
          <span
            className="flex min-w-0 items-center overflow-hidden whitespace-nowrap text-xs font-medium text-gray-900"
            data-testid="keyed-variable-primary"
            title={typeLabel ? `${fullPath} · ${typeLabel}` : fullPath}
          >
            <span className="min-w-0 truncate" data-testid="keyed-variable-base">
              {canonicalBase.name}
            </span>
            {canonicalBase.keys.map((key, index) => (
              <span key={`${key}:${index}`} className="shrink-0">
                <Key value={key} chainId={chainId} />
              </span>
            ))}
            <span className="shrink-0" data-testid="keyed-variable-leaf">.{finalSegment.name}</span>
          </span>
        </DetailPopover>
      </div>
    );
  }

  return (
    <div className="min-w-0 font-mono leading-tight" data-testid="keyed-variable-path">
      <div className="flex min-w-0 items-center">
        <span
          className="min-w-0 break-words text-xs font-medium text-gray-900"
          data-testid="keyed-variable-primary"
          title={fullPath}
        >
          {hasLeafField || stackKeys
            ? finalSegment.name
            : <InlineSegment segment={finalSegment} chainId={chainId} />}
        </span>
        <CopyButton
          value={fullPath}
          label="Copy full path"
          className="-my-1 ml-0.5 shrink-0 p-1 text-gray-400"
        />
      </div>
      {stackKeys ? (
        <div
          className="mt-0.5 space-y-0 text-[10px] text-gray-400"
          data-testid="keyed-variable-context"
        >
          {stackedLines.map((line, index) => (
            <div
              key={`${line.name}:${line.key}:${index}`}
              className="flex min-w-0 items-baseline gap-x-1 pl-2"
              data-testid={line.key ? 'keyed-variable-key-line' : undefined}
            >
              {line.separator && <span aria-hidden="true">›</span>}
              {line.name && <span>{line.name}</span>}
              {line.key && <Key value={line.key} chainId={chainId} />}
              {index === stackedLines.length - 1 && typeLabel && (
                <>
                  <span aria-hidden="true">·</span>
                  <span>{typeLabel}</span>
                </>
              )}
            </div>
          ))}
        </div>
      ) : (context.length > 0 || typeLabel) && (
        <div
          className="mt-0.5 flex flex-wrap items-baseline gap-x-1 text-[10px] text-gray-400"
          data-testid="keyed-variable-context"
        >
          {context.map((segment, index) => (
            <span key={`${segment.name}:${index}`} className="contents">
              {index > 0 && <span aria-hidden="true">›</span>}
              <InlineSegment segment={segment} chainId={chainId} />
            </span>
          ))}
          {context.length > 0 && typeLabel && <span aria-hidden="true">·</span>}
          {typeLabel && <span>{typeLabel}</span>}
        </div>
      )}
    </div>
  );
}
