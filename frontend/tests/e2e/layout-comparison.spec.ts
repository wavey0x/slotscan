import { expect, test, type Page } from '@playwright/test';

const FROM = '0x1111111111111111111111111111111111111111';
const TO = '0x2222222222222222222222222222222222222222';
const THIRD = '0x3333333333333333333333333333333333333333';
const IMPLEMENTATION = '0x4444444444444444444444444444444444444444';
const DELEGATE = '0x5555555555555555555555555555555555555555';
const FROM_HASH = `0x${'ab'.repeat(32)}`;
const TO_HASH = `0x${'cd'.repeat(32)}`;

function subject({
  input,
  kind = 'direct',
  code = input,
  name = 'Vault',
  status = 'ok',
  block = '0x7b',
  hash = FROM_HASH,
}: {
  input: string;
  kind?: 'direct' | 'proxy' | 'eip7702';
  code?: string;
  name?: string | null;
  status?: string;
  block?: string;
  hash?: string;
}) {
  return {
    input_address: input,
    storage_address: input,
    code_address: code,
    kind,
    block_ref: { number: block, hash },
    name,
    layout_status: status,
  };
}

function region({
  slot,
  end = slot,
  path,
  label = 'uint256',
  byteOffset = 0,
  byteSize = '32',
  root = false,
  scope = 'default',
  formula = null,
}: {
  slot: string;
  end?: string;
  path: string;
  label?: string;
  byteOffset?: number;
  byteSize?: string;
  root?: boolean;
  scope?: string;
  formula?: string | null;
}) {
  return {
    scope: {
      id: scope,
      kind: scope === 'default' ? 'default' : 'erc7201',
      root_slot: scope === 'default' ? '0x0' : slot,
      formula,
    },
    location: {
      slot,
      byte_offset: byteOffset,
      byte_size: byteSize,
      end_slot: end,
      is_root: root,
    },
    path,
    type: {
      label,
      kind: root ? 'mapping' : 'value',
      encoding: root ? 'mapping' : 'inplace',
      byte_size: byteSize,
      array_length: null,
      element_stride: null,
    },
  };
}

function comparisonEntry(
  id: string,
  kind: string,
  impact: 'conflict' | 'ambiguous' | 'none',
  fromRegion: ReturnType<typeof region> | null,
  toRegion: ReturnType<typeof region> | null,
  details = ['Objective detail one.', 'Objective detail two.'],
) {
  return {
    id,
    kind,
    impact,
    from_region: fromRegion,
    to_region: toRegion,
    details,
  };
}

function availableReport(overrides: Record<string, unknown> = {}) {
  const entries = [
    comparisonEntry(
      'unchanged',
      'unchanged',
      'none',
      region({
        slot: '0x2',
        path: 'owner',
        label: 'address',
        byteSize: '20',
      }),
      region({
        slot: '0x2',
        path: 'owner',
        label: 'address',
        byteSize: '20',
      }),
      ['The physical location and recursive storage shape are unchanged.'],
    ),
    comparisonEntry(
      'expanded',
      'shape_changed',
      'conflict',
      region({
        slot: '0x4',
        end: '0x5',
        path: 'config',
        label: 'Config',
        byteSize: '64',
      }),
      region({
        slot: '0x4',
        end: '0x8',
        path: 'config',
        label: 'ConfigV2',
        byteSize: '160',
      }),
    ),
    comparisonEntry(
      'mapping',
      'mapping_key_changed',
      'conflict',
      region({
        slot: '0x3',
        path: 'balances',
        label: 'mapping(address => uint256)',
        root: true,
      }),
      region({
        slot: '0x3',
        path: 'balances',
        label: 'mapping(bytes32 => uint256)',
        root: true,
      }),
    ),
    comparisonEntry(
      'moved',
      'moved',
      'conflict',
      region({ slot: '0x9', path: 'guardian', label: 'address', byteSize: '20' }),
      region({ slot: '0xc', path: 'guardian', label: 'address', byteSize: '20' }),
    ),
    comparisonEntry(
      'added',
      'addition',
      'none',
      null,
      region({ slot: '0xd', path: 'paused', label: 'bool', byteSize: '1' }),
    ),
    comparisonEntry(
      'removed',
      'removed',
      'conflict',
      region({ slot: '0xe', path: 'deprecated' }),
      null,
    ),
  ];
  return {
    chain_id: 1,
    verdict: 'conflicts',
    from_subject: subject({ input: FROM, kind: 'proxy', code: IMPLEMENTATION, name: 'ProxyVault' }),
    to_subject: subject({
      input: TO,
      kind: 'eip7702',
      code: DELEGATE,
      name: 'DelegateVault',
      block: '0x1c8',
      hash: TO_HASH,
    }),
    summary: {
      conflicts: 4,
      ambiguous: 0,
      changes: 1,
      unchanged: 1,
    },
    entries,
    limitations: [],
    ...overrides,
  };
}

async function mockComparison(
  page: Page,
  response: ReturnType<typeof availableReport> = availableReport(),
) {
  const requests: URL[] = [];
  await page.route('**/api/slotscan/layout-comparisons/1?*', async (route) => {
    requests.push(new URL(route.request().url()));
    await route.fulfill({ json: response });
  });
  return requests;
}

test('prefill focuses To, validates locally, and submits URL-owned intent with Enter', async ({ page }) => {
  const requests = await mockComparison(page);
  await page.goto(`/1/compare?from=${FROM}`);

  const from = page.getByLabel('From', { exact: true });
  const to = page.getByLabel('To', { exact: true });
  await expect(from).toHaveValue(FROM);
  await expect(to).toBeFocused();
  await to.fill('not-an-address');
  await to.press('Enter');
  await expect(page.getByText('Enter a valid Ethereum address.')).toBeVisible();
  expect(requests).toHaveLength(0);

  await to.fill(TO);
  await to.press('Enter');
  await expect(page).toHaveURL(new RegExp(`from=${FROM}.*to=${TO}`));
  await expect(page.getByRole('table')).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0].searchParams.get('from_address')).toBe(FROM);
  expect(requests[0].searchParams.get('to_address')).toBe(TO);
});

test('malformed exact-link hashes fail inline without making an API request', async ({ page }) => {
  const requests = await mockComparison(page);
  await page.goto(
    `/1/compare?from=${FROM}&to=${TO}&fromBlock=100&fromBlockHash=0x1234`,
  );

  await expect(page.getByLabel('From block')).toHaveAttribute(
    'aria-invalid',
    'true',
  );
  await expect(
    page.getByText('The exact block hash is invalid; edit this block to refresh it.'),
  ).toBeVisible();
  expect(requests).toHaveLength(0);

  await page.getByLabel('From block').fill('101');
  await page.getByRole('button', { name: 'Compare' }).click();
  await expect(page.getByRole('table')).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0].searchParams.get('from_block')).toBe('101');
  expect(requests[0].searchParams.has('from_block_hash')).toBe(false);

  await page.goto(
    `/1/compare?from=${FROM}&to=${TO}&toBlockHash=${TO_HASH}`,
  );
  await expect(page.getByLabel('To block')).toBeVisible();
  await expect(page.getByText('The exact hash requires a block number.')).toBeVisible();
  expect(requests).toHaveLength(1);
});

test('Swap moves selectors and exact hashes, while an edited side drops its stale hash', async ({ page }) => {
  await mockComparison(page);
  await page.goto(
    `/1/compare?from=${FROM}&to=${TO}`
    + `&fromBlock=100&fromBlockHash=${FROM_HASH}`
    + `&toBlock=200&toBlockHash=${TO_HASH}`,
  );

  await expect(page.getByLabel('From block')).toBeVisible();
  await expect(page.getByLabel('To block')).toBeVisible();
  await expect(page.getByLabel('From block')).toHaveValue('100');
  await expect(page.getByLabel('To block')).toHaveValue('200');
  await page.getByRole('button', { name: 'Swap' }).click();
  await expect(page.getByLabel('From', { exact: true })).toHaveValue(TO);
  await expect(page.getByLabel('From block')).toHaveValue('200');
  await page.getByRole('button', { name: 'Compare' }).click();
  await expect(page).toHaveURL(new RegExp(`from=${TO}.*to=${FROM}`));
  let url = new URL(page.url());
  expect(url.searchParams.get('fromBlockHash')).toBe(TO_HASH);
  expect(url.searchParams.get('toBlockHash')).toBe(FROM_HASH);

  await page.getByLabel('From', { exact: true }).fill(THIRD);
  await page.getByRole('button', { name: 'Compare' }).click();
  await expect(page).toHaveURL(new RegExp(`from=${THIRD}`));
  url = new URL(page.url());
  expect(url.searchParams.get('from')).toBe(THIRD);
  expect(url.searchParams.get('fromBlock')).toBe('200');
  expect(url.searchParams.has('fromBlockHash')).toBe(false);
  expect(url.searchParams.get('toBlockHash')).toBe(FROM_HASH);
});

test('resolved subjects, filter counts, and browser history remain reproducible', async ({
  page,
}) => {
  await mockComparison(page);
  await page.goto(`/1/compare?from=${FROM}&to=${TO}`);

  await expect(page.getByText('ProxyVault', { exact: true })).toBeVisible();
  await expect(page.getByText('DelegateVault', { exact: true })).toBeVisible();
  await expect(page.getByText('Storage', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Code', { exact: true }).first()).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'All 6', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  await expect(
    page.getByRole('button', { name: 'Changes 5', exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Conflicts 4', exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: 'Copy exact link' })).toHaveCount(0);
  await expect(page.getByText(/does not analyze values, initialization/)).toHaveCount(0);

  await page.getByLabel('To', { exact: true }).fill(THIRD);
  await page.getByRole('button', { name: 'Compare' }).click();
  await expect(page).toHaveURL(new RegExp(`to=${THIRD}`));
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`to=${TO}`));
  await expect(page.getByLabel('To', { exact: true })).toHaveValue(TO);
});

test('neutral counts replace verdict prose and identical layouts show their rows', async ({ page }) => {
  const unchangedEntries = [
    comparisonEntry(
      'unchanged',
      'unchanged',
      'none',
      region({
        slot: '0x2',
        path: 'owner',
        label: 'address',
        byteSize: '20',
      }),
      region({
        slot: '0x2',
        path: 'owner',
        label: 'address',
        byteSize: '20',
      }),
      ['The physical location and recursive storage shape are unchanged.'],
    ),
  ];
  let response = availableReport({
    verdict: 'no_conflicts',
    summary: {
      conflicts: 0,
      ambiguous: 0,
      changes: 0,
      unchanged: 1,
    },
    entries: unchangedEntries,
  });
  await page.route('**/api/slotscan/layout-comparisons/1?*', async (route) => {
    await route.fulfill({ json: response });
  });

  await page.goto(`/1/compare?from=${FROM}&to=${TO}`);
  await expect(
    page.getByRole('button', { name: 'All 1', exact: true }),
  ).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', {
    name: 'Expand details for slot 2 · bytes 0–19',
  })).toHaveCount(0);
  await expect(page.getByText('owner', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('No matching rows.')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'No storage conflicts' })).toHaveCount(0);

  response = availableReport({
    verdict: 'indeterminate',
    summary: {
      conflicts: 0,
      ambiguous: 1,
      changes: 0,
      unchanged: 1,
    },
  });
  await page.reload();
  await expect(
    page.getByRole('button', { name: 'Changes 1', exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Comparison indeterminate' })).toHaveCount(0);
  await expect(page.getByText(/overall safety/)).toHaveCount(0);
});

test('request failures offer a retry without losing submitted intent', async ({ page }) => {
  let attempts = 0;
  await page.route('**/api/slotscan/layout-comparisons/1?*', async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({
        status: 502,
        json: {
          detail: {
            error: 'Provider unavailable',
            code: 'UPSTREAM_FAILURE',
          },
        },
      });
      return;
    }
    await route.fulfill({ json: availableReport() });
  });

  await page.goto(`/1/compare?from=${FROM}&to=${TO}`);
  await expect(page.getByText('Comparison request failed')).toBeVisible();
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`from=${FROM}.*to=${TO}`));
  expect(attempts).toBe(2);
});

test('the comparison table keeps Location as the anchor and exposes all objective details', async ({ page }) => {
  await mockComparison(page);
  await page.goto(`/1/compare?from=${FROM}&to=${TO}`);

  const table = page.getByRole('table');
  await expect(table.getByRole('columnheader')).toHaveText(['Location', 'From', 'To']);
  const filterBox = await page.getByRole('group', { name: 'Rows' }).boundingBox();
  const tableBox = await table.boundingBox();
  expect(filterBox).not.toBeNull();
  expect(tableBox).not.toBeNull();
  expect(filterBox!.y + filterBox!.height).toBeLessThanOrEqual(tableBox!.y);
  await expect(table.getByRole('button', { name: 'Expand details for slots 4–5 → slots 4–8' })).toBeVisible();
  await expect(table.getByRole('button', { name: 'Expand details for root slot 3' })).toBeVisible();
  await expect(table.getByRole('button', { name: 'Expand details for slot 9 · bytes 0–19 → slot 12 · bytes 0–19' })).toBeVisible();
  await expect(table.getByRole('button', { name: 'Expand details for — → slot 13 · bytes 0–0' })).toBeVisible();
  await expect(table.getByRole('button', { name: 'Expand details for slot 14 → —' })).toBeVisible();
  await expect(table.getByRole('button', {
    name: 'Expand details for slot 2 · bytes 0–19',
  })).toHaveCount(0);
  await expect(table.getByText('owner', { exact: true }).first()).toBeVisible();
  await expect(table.getByText('Result', { exact: true })).toHaveCount(0);
  await expect(table.getByText('Change', { exact: true })).toHaveCount(0);

  await page.getByRole('button', { name: 'Expand details for slots 4–5 → slots 4–8' }).click();
  await expect(page.getByRole('listitem').filter({ hasText: 'Objective detail one.' })).toBeVisible();
  await expect(page.getByRole('listitem').filter({ hasText: 'Objective detail two.' })).toBeVisible();
  await expect(page.getByText('Storage conflict.', { exact: true }).first()).toBeAttached();

  await page.getByRole('button', { name: 'Changes' }).click();
  await expect(table.getByText('owner', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Conflicts' }).click();
  await expect(table.getByRole('button', { name: 'Expand details for — → slot 13 · bytes 0–0' })).toBeHidden();
});

test('search appears only for large reports and filters paths, labels, scopes, and slots', async ({ page }) => {
  const entries = Array.from({ length: 50 }, (_, index) => comparisonEntry(
    `entry-${index}`,
    'addition',
    'none',
    null,
    region({
      slot: `0x${(index + 20).toString(16)}`,
      path: index === 17 ? 'needlePath' : `value${index}`,
      label: index === 16 ? 'NeedleType' : 'uint256',
    }),
    ['New declaration.'],
  ));
  await mockComparison(page, availableReport({
    verdict: 'no_conflicts',
    summary: { conflicts: 0, ambiguous: 0, changes: 50, unchanged: 0 },
    entries,
  }));
  await page.goto(`/1/compare?from=${FROM}&to=${TO}`);

  const search = page.getByRole('textbox', { name: 'Search comparison rows' });
  await expect(search).toBeVisible();
  await search.fill('needlePath');
  await expect(page.getByText('needlePath', { exact: true })).toBeVisible();
  await expect(page.getByText('value0', { exact: true })).toBeHidden();
  await search.fill('0x24');
  await expect(page.getByText('value16', { exact: true })).toBeVisible();
});

test('unavailable reports preserve a successful side and explain exact-evidence failure', async ({ page }) => {
  await mockComparison(page, availableReport({
    verdict: 'unavailable',
    from_subject: subject({
      input: FROM,
      name: null,
      status: 'non_exact',
    }),
    to_subject: subject({ input: TO, name: 'ExactVault' }),
    summary: null,
    entries: [],
    limitations: ['from_non_exact'],
  }));
  await page.goto(`/1/compare?from=${FROM}&to=${TO}`);

  await expect(page.getByRole('heading', { name: 'Layout unavailable' })).toBeVisible();
  await expect(page.getByText('Layout evidence is not exact')).toBeVisible();
  await expect(page.getByText('ExactVault', { exact: true })).toBeVisible();
  await expect(page.getByText('The From layout depends on inferred or non-exact evidence.')).toBeVisible();
  await expect(page.getByText(/does not analyze values/)).toHaveCount(0);
});

test('narrow and dark layouts remain contained and keyboard accessible', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem('slotscan-theme', 'dark'));
  await mockComparison(page);
  await page.goto(`/1/compare?from=${FROM}&to=${TO}`);

  await expect(page.locator('html')).toHaveClass(/dark/);
  await page.getByRole('button', { name: 'Changes' }).focus();
  await page.keyboard.press('ArrowRight');
  await page.getByRole('button', { name: 'All' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText('owner', { exact: true }).first()).toBeVisible();

  const overflowing = await page.evaluate(() => Array.from(document.querySelectorAll<HTMLElement>('body *'))
    .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
    .map((element) => `${element.tagName.toLowerCase()}.${element.className}`));
  expect(overflowing).toEqual([]);
});
