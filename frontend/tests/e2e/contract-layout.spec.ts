import { expect, test, type Page } from '@playwright/test';

const ADDRESS = '0x1234567890abcdef1234567890abcdef12345678';
const DELEGATE = '0x2222222222222222222222222222222222222222';
const IMPLEMENTATION = '0x3333333333333333333333333333333333333333';
const BLOCK_HASH = `0x${'ab'.repeat(32)}`;
const LAYOUT_ID = `sha256:${'1'.repeat(64)}`;

type ViewOverrides = {
  name?: string | null;
  contract?: Record<string, unknown>;
  variables?: Record<string, unknown>[];
  types?: Record<string, Record<string, unknown>>;
  values?: Record<string, unknown>[];
  layoutStatus?: 'ok' | 'unverified' | 'unsupported';
  valuesStatus?: 'ok' | 'error' | 'unavailable';
  blockNumber?: string;
};

function scalarType(id = 't_uint256', label = 'uint256', bytes = '32') {
  return {
    id,
    label,
    kind: 'value',
    encoding: 'inplace',
    num_bytes: bytes,
    base_type: null,
    element_type: null,
    array_length: null,
    key_type: null,
    value_type: null,
    members: [],
  };
}

function variable(
  declarationId: string,
  name: string,
  slot: string,
  typeId = 't_uint256',
  typeLabel = 'uint256',
) {
  return {
    declaration_id: declarationId,
    name,
    slot,
    byte_offset: 0,
    byte_size: '32',
    type_id: typeId,
    type_label: typeLabel,
    provenance: 'compiler_layout',
    confidence: 'exact',
  };
}

function value(
  declarationId: string,
  path: string,
  slot: string,
  decoded: unknown,
  status = 'ok',
) {
  return {
    declaration_id: declarationId,
    path,
    status,
    slot,
    byte_offset: 0,
    value_encoded: status === 'ok' ? `0x${'0'.repeat(63)}1` : null,
    value_decoded: status === 'ok' ? decoded : null,
  };
}

function storageView(overrides: ViewOverrides = {}) {
  const layoutStatus = overrides.layoutStatus ?? 'ok';
  return {
    block_ref: {
      number: overrides.blockNumber ?? '0x7b',
      hash: BLOCK_HASH,
    },
    contract: {
      address: ADDRESS,
      storage_address: ADDRESS,
      effective_code_address: ADDRESS,
      name: overrides.name === undefined ? 'MockVault' : overrides.name,
      is_verified: true,
      is_proxy: false,
      proxy_type: null,
      ...overrides.contract,
    },
    layout_id: layoutStatus === 'ok' ? LAYOUT_ID : null,
    layout: {
      status: layoutStatus,
      variables: overrides.variables ?? [],
      types: overrides.types ?? {},
      storage_rules: layoutStatus === 'ok'
        ? {
            mapping_preimage_order: 'key_then_slot',
            array_storage_scheme: 'solidity',
          }
        : null,
    },
    values: {
      status: overrides.valuesStatus ?? (layoutStatus === 'ok' ? 'ok' : 'unavailable'),
      items: overrides.values ?? [],
      error_code: overrides.valuesStatus === 'error' ? 'STORAGE_READ_FAILED' : null,
    },
  };
}

async function mockView(page: Page, overrides: ViewOverrides = {}) {
  await page.route(`**/api/slotscan/contracts/1/${ADDRESS}/storage-view?*`, async (route) => {
    await route.fulfill({ json: storageView(overrides) });
  });
}

test('direct contracts render one coherent exact-block response', async ({ page }) => {
  await mockView(page, {
    variables: [variable('decl:0', 'owner', '0x2')],
    types: { t_uint256: scalarType() },
    values: [value('decl:0', 'owner', '0x2', '42')],
  });
  await page.goto(`/1/${ADDRESS}`);

  const header = page.locator('main header');
  await expect(header.getByRole('heading', { name: 'MockVault' })).toBeVisible();
  await expect(header.getByText(/Verified/)).toBeVisible();
  await expect(page.getByText('Block 123')).toBeVisible();
  await expect(page.getByText('42', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Copy owner value' })).toHaveCount(0);
  await expect(page.getByRole('group', { name: 'Values' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Compare layout →' })).toHaveAttribute(
    'href',
    `/1/compare?from=${ADDRESS}`,
  );
});

test('proxy and delegated views keep storage and effective code addresses distinct', async ({ page }) => {
  await mockView(page, {
    name: 'DelegateWallet',
    contract: { effective_code_address: DELEGATE },
  });
  await page.goto(`/1/${ADDRESS}`);
  await expect(page.locator('main header').getByText(/Delegated EOA/)).toBeVisible();
  await expect(page.getByText(/Storage at/)).toBeVisible();
  await expect(page.getByText(/Executing code from/)).toBeVisible();
  await expect(page.getByRole('link', { name: '0x2222...2222' })).toBeVisible();

  await page.unrouteAll({ behavior: 'wait' });
  await mockView(page, {
    name: 'ProxyVault',
    contract: {
      effective_code_address: IMPLEMENTATION,
      is_proxy: true,
      proxy_type: 'eip1967',
    },
  });
  await page.goto(`/1/${ADDRESS}`);
  await expect(page.locator('main header').getByText('Proxy · Verified')).toBeVisible();
  await expect(page.getByText(/Implementation/)).toBeVisible();
  await expect(page.getByRole('link', { name: '0x3333...3333' })).toBeVisible();
});

test('high slots stay exact strings in the table and disclosure', async ({ page }) => {
  const highSlot = `0x8${'0'.repeat(63)}`;
  await page.setViewportSize({ width: 390, height: 844 });
  await mockView(page, {
    variables: [variable('decl:0', 'highValue', highSlot)],
    types: { t_uint256: scalarType() },
    values: [value('decl:0', 'highValue', highSlot, '7')],
  });
  await page.goto(`/1/${ADDRESS}`);

  const slotCell = page.getByTestId('layout-slot');
  await expect(slotCell).toBeVisible();
  await expect(slotCell).toHaveAttribute('title', highSlot);
  await page.getByText('highValue', { exact: true }).click();
  await expect(page.getByRole('dialog').getByText(highSlot, { exact: true })).toBeVisible();
});

test('address values stay on one line and use the full table width on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockView(page, {
    variables: [
      variable('decl:0', 'owner', '0x2', 't_address', 'address'),
      variable('decl:1', 'max_fee', '0x4', 't_array', 'uint256[9]'),
    ],
    types: {
      t_uint256: scalarType(),
      t_address: scalarType('t_address', 'address', '20'),
      t_array: {
        ...scalarType('t_array', 'uint256[9]'),
        kind: 'array',
        encoding: 'inplace',
        element_type: 't_uint256',
        array_length: '9',
      },
    },
    values: [
      value('decl:0', 'owner', '0x2', '0xff12b7B0dF9a2A96CBc09b3822B4Db43a575cCEE'),
      value('decl:1', 'max_fee', '0x4', null, 'on_demand'),
    ],
  });
  await page.goto(`/1/${ADDRESS}`);

  // An expanded lookup row's spanning cell must not add a phantom column.
  await page.getByRole('button', { name: 'Expand max_fee' }).click();

  const compactValue = page.getByText('0xff12...cCEE', { exact: true });
  await expect(compactValue).toBeVisible();
  const valueBox = (await compactValue.boundingBox())!;
  expect(valueBox.height).toBeLessThanOrEqual(20);
  const slotRight = await page.getByTestId('layout-slot').first()
    .evaluate((element) => element.getBoundingClientRect().right);
  const tableRight = await page.getByRole('table').evaluate((element) => element.getBoundingClientRect().right);
  expect(tableRight - slotRight).toBeLessThanOrEqual(1);
});

test('packed values sharing one word remain separate logical rows', async ({ page }) => {
  await mockView(page, {
    variables: [
      variable('decl:0', 'enabled', '0x5', 't_bool', 'bool'),
      variable('decl:1', 'count', '0x5', 't_uint8', 'uint8'),
    ],
    types: {
      t_bool: scalarType('t_bool', 'bool', '1'),
      t_uint8: scalarType('t_uint8', 'uint8', '1'),
    },
    values: [
      value('decl:0', 'enabled', '0x5', true),
      value('decl:1', 'count', '0x5', '9'),
    ],
  });
  await page.goto(`/1/${ADDRESS}`);

  await expect(page.getByText('true', { exact: true })).toBeVisible();
  await expect(page.getByText('9', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /Copy (enabled|count) value/ })).toHaveCount(0);
});

test('a value-read failure keeps the valid layout visible', async ({ page }) => {
  await mockView(page, {
    variables: [variable('decl:0', 'owner', '0x2')],
    types: { t_uint256: scalarType() },
    valuesStatus: 'error',
  });
  await page.goto(`/1/${ADDRESS}`);

  await expect(page.getByText('Values could not be read at this block.')).toBeVisible();
  await expect(page.getByText('owner', { exact: true })).toBeVisible();
});

test('a failed refresh keeps and labels the last exact response', async ({ page }) => {
  let failRefresh = false;
  await page.route(`**/api/slotscan/contracts/1/${ADDRESS}/storage-view?*`, async (route) => {
    if (failRefresh) {
      await route.fulfill({
        status: 502,
        json: { detail: { error: 'RPC unavailable', code: 'RPC_ERROR' } },
      });
      return;
    }
    await route.fulfill({ json: storageView() });
  });
  await page.goto(`/1/${ADDRESS}`);
  await expect(page.getByText('Block 123')).toBeVisible();

  failRefresh = true;
  await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')));

  await expect(page.getByText('Refresh failed · showing last exact block')).toBeVisible();
  await expect(page.getByText('Block 123')).toBeVisible();
});

test('unsupported aggregates do not offer a query control', async ({ page }) => {
  const config = {
    ...scalarType('config', 'struct Config'),
    kind: 'struct',
    members: [{
      name: 'limit',
      slot: '0x0',
      byte_offset: 0,
      byte_size: '32',
      type_id: 't_uint256',
      label: 'uint256',
    }],
  };
  const mapping = {
    ...scalarType('mapping', 'mapping(address => struct Config)'),
    kind: 'mapping',
    encoding: 'mapping',
    key_type: 't_address',
    value_type: config.id,
  };
  await mockView(page, {
    variables: [variable('decl:0', 'configs', '0x7', mapping.id, mapping.label)],
    types: {
      mapping,
      config,
      t_address: scalarType('t_address', 'address', '20'),
      t_uint256: scalarType(),
    },
    values: [value('decl:0', 'configs', '0x7', null, 'unsupported')],
  });

  await page.goto(`/1/${ADDRESS}`);

  await expect(page.getByRole('button', { name: 'Expand configs' })).toHaveCount(0);
  await expect(page.getByText('expand to query')).toHaveCount(0);
});

test('mapping queries send raw keys and exact identities, never a computed slot', async ({ page }) => {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  const mapping = {
    id: 'mapping',
    label: 'mapping(address => uint256)',
    kind: 'mapping',
    encoding: 'mapping',
    num_bytes: '32',
    base_type: null,
    element_type: null,
    array_length: null,
    key_type: 't_address',
    value_type: 't_uint256',
    members: [],
  };
  await mockView(page, {
    variables: [variable('decl:0', 'balances', '0x7', 'mapping', mapping.label)],
    types: {
      mapping,
      t_address: scalarType('t_address', 'address', '20'),
      t_uint256: scalarType(),
    },
    values: [value('decl:0', 'balances', '0x7', null, 'on_demand')],
  });
  let requestBody: Record<string, unknown> | null = null;
  await page.route('**/api/slotscan/storage/query', async (route) => {
    requestBody = route.request().postDataJSON();
    await route.fulfill({
      json: {
        block_ref: { number: '0x7b', hash: BLOCK_HASH },
        layout_id: LAYOUT_ID,
        declaration_id: 'decl:0',
        path: `balances[${ADDRESS}]`,
        location: { slot: '0xabc', byte_offset: 0, byte_size: 32 },
        value_encoded: `0x${'0'.repeat(63)}5`,
        value_decoded: '5',
        array_length: null,
      },
    });
  });
  await page.goto(`/1/${ADDRESS}`);

  await page.getByRole('button', { name: 'Expand balances' }).click();
  await page.getByPlaceholder('0x… address').fill(ADDRESS);
  await page.getByRole('button', { name: 'Lookup' }).click();
  await expect(page.getByText('0xabc', { exact: true })).toBeVisible();
  const keyCopy = page.getByRole('button', { name: 'Copy mapping key 0x1234...5678' });
  await expect(keyCopy).toBeVisible();
  await keyCopy.click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(ADDRESS);

  expect(requestBody).toMatchObject({
    chain_id: '1',
    address: ADDRESS,
    block_ref: { number: '0x7b', hash: BLOCK_HASH },
    layout_id: LAYOUT_ID,
    access: {
      declaration_id: 'decl:0',
      steps: [{ kind: 'mapping_key', value: ADDRESS }],
    },
  });
  expect(JSON.stringify(requestBody)).not.toContain('"slot"');
  expect(JSON.stringify(requestBody)).not.toContain('encoded');
});

test('nested mappings preserve the raw ordered key sequence', async ({ page }) => {
  const outer = {
    id: 'outer',
    label: 'mapping(address => mapping(uint256 => uint256))',
    kind: 'mapping',
    encoding: 'mapping',
    num_bytes: '32',
    base_type: null,
    element_type: null,
    array_length: null,
    key_type: 't_address',
    value_type: 'inner',
    members: [],
  };
  const inner = {
    ...outer,
    id: 'inner',
    label: 'mapping(uint256 => uint256)',
    key_type: 't_uint256',
    value_type: 't_uint256',
  };
  await mockView(page, {
    variables: [variable('decl:0', 'votes', '0x7', 'outer', outer.label)],
    types: {
      outer,
      inner,
      t_address: scalarType('t_address', 'address', '20'),
      t_uint256: scalarType(),
    },
    values: [value('decl:0', 'votes', '0x7', null, 'on_demand')],
  });
  let steps: unknown;
  await page.route('**/api/slotscan/storage/query', async (route) => {
    steps = route.request().postDataJSON().access.steps;
    await route.fulfill({
      json: {
        block_ref: { number: '0x7b', hash: BLOCK_HASH },
        layout_id: LAYOUT_ID,
        declaration_id: 'decl:0',
        path: 'votes',
        location: { slot: '0xdef', byte_offset: 0, byte_size: 32 },
        value_encoded: `0x${'0'.repeat(63)}1`,
        value_decoded: '1',
        array_length: null,
      },
    });
  });
  await page.goto(`/1/${ADDRESS}`);
  await page.getByRole('button', { name: 'Expand votes' }).click();
  await page.getByPlaceholder('0x… address').fill(ADDRESS);
  await page.getByPlaceholder('integer').fill('5');
  await page.getByRole('button', { name: 'Lookup' }).click();

  expect(steps).toEqual([
    { kind: 'mapping_key', value: ADDRESS },
    { kind: 'mapping_key', value: '5' },
  ]);
});

for (const arrayKind of ['fixed', 'dynamic'] as const) {
  test(`${arrayKind} array queries keep the index string and exact block`, async ({ page }) => {
    const dynamic = arrayKind === 'dynamic';
    const array = {
      id: 'array',
      label: dynamic ? 'uint32[]' : 'uint32[8]',
      kind: 'array',
      encoding: dynamic ? 'dynamic_array' : 'inplace',
      num_bytes: dynamic ? '32' : '256',
      base_type: null,
      element_type: 't_uint32',
      array_length: dynamic ? null : '8',
      key_type: null,
      value_type: null,
      members: [],
    };
    await mockView(page, {
      variables: [variable('decl:0', 'items', '0x9', 'array', array.label)],
      types: { array, t_uint32: scalarType('t_uint32', 'uint32', '4') },
      values: [value('decl:0', 'items', '0x9', null, 'on_demand')],
    });
    let requestBody: Record<string, any> | null = null;
    await page.route('**/api/slotscan/storage/query', async (route) => {
      requestBody = route.request().postDataJSON();
      await route.fulfill({
        json: {
          block_ref: { number: '0x7b', hash: BLOCK_HASH },
          layout_id: LAYOUT_ID,
          declaration_id: 'decl:0',
          path: 'items[3]',
          location: { slot: '0xaaa', byte_offset: 12, byte_size: 4 },
          value_encoded: `0x${'0'.repeat(63)}3`,
          value_decoded: '3',
          array_length: dynamic ? '4' : null,
        },
      });
    });
    await page.goto(`/1/${ADDRESS}`);
    await page.getByRole('button', { name: 'Expand items' }).click();
    await page.getByPlaceholder(dynamic ? 'Enter array index' : 'Enter index (length 8)').fill('3');
    await page.getByRole('button', { name: 'Lookup' }).click();

    expect(requestBody!.access.steps).toEqual([{ kind: 'array_index', value: '3' }]);
    expect(requestBody!.block_ref).toEqual({ number: '0x7b', hash: BLOCK_HASH });
    expect(JSON.stringify(requestBody)).not.toContain('"slot"');
  });
}

test('invalid array syntax is rejected before any query request', async ({ page }) => {
  const array = {
    id: 'array',
    label: 'uint32[]',
    kind: 'array',
    encoding: 'dynamic_array',
    num_bytes: '32',
    base_type: null,
    element_type: 't_uint32',
    array_length: null,
    key_type: null,
    value_type: null,
    members: [],
  };
  await mockView(page, {
    variables: [variable('decl:0', 'items', '0x9', 'array', array.label)],
    types: { array, t_uint32: scalarType('t_uint32', 'uint32', '4') },
    values: [value('decl:0', 'items', '0x9', null, 'on_demand')],
  });
  let queryCount = 0;
  await page.route('**/api/slotscan/storage/query', async (route) => {
    queryCount += 1;
    await route.abort();
  });
  await page.goto(`/1/${ADDRESS}`);
  await page.getByRole('button', { name: 'Expand items' }).click();
  await page.getByPlaceholder('Enter array index').fill('-1');
  await page.getByRole('button', { name: 'Lookup' }).click();

  await expect(page.getByText('Enter a non-negative decimal or hexadecimal index')).toBeVisible();
  expect(queryCount).toBe(0);
});
