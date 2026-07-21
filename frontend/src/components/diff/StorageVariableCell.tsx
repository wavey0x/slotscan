import { KeyedVariablePath } from './KeyedVariablePath';
import type { StorageIdentity } from './storageIdentity';
import { storageIdentityMetadata } from './storageIdentity';

export function StorageVariableCell({
  identity,
  chainId,
  testId,
  metadataTestId,
}: {
  identity: StorageIdentity;
  chainId: string;
  testId?: string;
  metadataTestId?: string;
}) {
  const metadata = storageIdentityMetadata(identity);

  return (
    <div className="min-w-0 font-mono leading-tight" data-testid={testId}>
      {identity.path?.includes('[') ? (
        <KeyedVariablePath
          path={identity.path}
          typeLabel={metadata}
          chainId={chainId}
        />
      ) : (
        <>
          <div className="min-w-0 break-words text-xs font-medium text-gray-900 [overflow-wrap:anywhere]">
            {identity.primary}
          </div>
          {metadata && (
            <div
              className="mt-0.5 min-w-0 truncate text-[10px] text-gray-400"
              data-testid={metadataTestId}
            >
              {metadata}
            </div>
          )}
        </>
      )}
    </div>
  );
}
