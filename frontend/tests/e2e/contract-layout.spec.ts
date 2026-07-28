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
    storage: null,
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
      layout_provenance: 'verified_source',
      layout_source_address: ADDRESS,
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
  await expect(page.getByRole('link', { name: 'Compare storage layout' })).toHaveAttribute(
    'href',
    `/1/compare?from=${ADDRESS}`,
  );
});

test('resolved dynamic strings disclose inline and computed storage', async ({ page }) => {
  const encodedName = '0x50656e646c65204d61726b65740000000000000000000000000000000000001a';
  const stringType = {
    ...scalarType('t_string_storage', 'string'),
    encoding: 'bytes',
  };
  await mockView(page, {
    variables: [
      variable('decl:0', '_name', '0x3', stringType.id, stringType.label),
      variable('decl:1', '_description', '0x4', stringType.id, stringType.label),
    ],
    types: {
      [stringType.id]: stringType,
    },
    values: [
      {
        ...value('decl:0', '_name', '0x3', 'Pendle Market'),
        value_encoded: encodedName,
        storage: {
          regions: [
            { role: 'inline', slot: '0x3', slot_count: '1' },
          ],
        },
      },
      {
        ...value('decl:1', '_description', '0x4', 'Dynamic storage data'),
        storage: {
          regions: [
            { role: 'length', slot: '0x4', slot_count: '1' },
            { role: 'data', slot: '0x1000', slot_count: '3' },
          ],
        },
      },
    ],
  });
  await page.goto(`/1/${ADDRESS}`);

  const nameRow = page.getByRole('row').filter({
    has: page.getByText('_name', { exact: true }),
  });
  await expect(nameRow).toContainText('Pendle Market');
  await expect(nameRow.locator('td').nth(3)).toHaveText('3');
  await nameRow.locator('td').nth(3).locator('[aria-haspopup="dialog"]').focus();
  const inlineDetail = page.getByRole('dialog', {
    name: 'Storage location: inline 0x3',
  });
  await expect(inlineDetail.getByText('inline', { exact: true })).toBeVisible();
  await expect(inlineDetail.getByText('3', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');

  const descriptionRow = page.getByRole('row').filter({
    has: page.getByText('_description', { exact: true }),
  });
  await expect(descriptionRow).toContainText('Dynamic storage data');
  await expect(descriptionRow.locator('td').nth(3)).toHaveText('4');
  await descriptionRow.locator('td').nth(3).locator('[aria-haspopup="dialog"]').focus();
  const computedDetail = page.getByRole('dialog', {
    name: 'Storage location: length 0x4, data 0x1000–0x1002',
  });
  await expect(computedDetail.getByText('length', { exact: true })).toBeVisible();
  await expect(computedDetail.getByText('4', { exact: true })).toBeVisible();
  await expect(computedDetail.getByText('data', { exact: true })).toBeVisible();
  await expect(computedDetail.getByText('0x1000–0x1002', { exact: true })).toBeVisible();
  await expect(
    computedDetail.getByTestId('storage-computed-occupancy').locator('span'),
  ).toHaveCount(3);
  await expect(
    computedDetail.getByRole('button', { name: 'Copy data slot range' }),
  ).toBeVisible();
  await page.keyboard.press('Escape');

  await page.getByRole('button', { name: 'Hex' }).click();
  await expect(nameRow).toContainText('0x50656e...00001a');
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

test('bytecode-equivalent layouts keep the target visibly unverified', async ({ page }) => {
  await mockView(page, {
    contract: {
      is_verified: false,
      layout_provenance: 'bytecode_equivalent',
      layout_source_address: IMPLEMENTATION,
    },
  });
  await page.goto(`/1/${ADDRESS}`);

  await expect(page.locator('main header').getByText('Unverified')).toBeVisible();
  await expect(
    page.getByText(/Layout from verified bytecode-equivalent/),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Copy layout source address' }),
  ).toBeVisible();
});

test('high slots use canonical compact notation with full disclosure', async ({ page }) => {
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
  const compactSlot = slotCell.getByText('0x80…00', { exact: true });
  await expect(compactSlot).toBeVisible();
  await compactSlot.click();
  const detail = page.getByRole('dialog');
  await expect(detail.getByText(highSlot, { exact: true })).toBeVisible();
  await expect(detail.getByRole('button', { name: 'Copy slot' })).toBeVisible();
});

test('long type labels get responsive space and an accessible full disclosure', async ({ page }) => {
  const typeLabel = 'mapping(address => DeployInfo)';
  const mapping = {
    ...scalarType('mapping', typeLabel),
    kind: 'mapping',
    encoding: 'mapping',
    key_type: 't_address',
    value_type: 't_uint256',
  };
  await page.setViewportSize({ width: 800, height: 844 });
  await mockView(page, {
    variables: [variable('decl:0', 'deployInfo', '0x4', mapping.id, typeLabel)],
    types: {
      mapping,
      t_address: scalarType('t_address', 'address', '20'),
      t_uint256: scalarType(),
    },
    values: [value('decl:0', 'deployInfo', '0x4', null, 'unsupported')],
  });
  await page.goto(`/1/${ADDRESS}`);

  const typeHeader = page.getByRole('columnheader', { name: 'Type' });
  const columnWidth = () => typeHeader.evaluate(
    (element) => Math.round(element.getBoundingClientRect().width),
  );
  const tabletWidth = await columnWidth();
  expect(tabletWidth).toBeGreaterThanOrEqual(176);
  expect(tabletWidth).toBeLessThanOrEqual(192);

  await page.setViewportSize({ width: 1200, height: 844 });
  await expect.poll(columnWidth).toBeGreaterThanOrEqual(tabletWidth + 24);
  await expect.poll(columnWidth).toBeLessThanOrEqual(224);

  await page.getByText(typeLabel, { exact: true }).locator('..').focus();
  const dialog = page.getByRole('dialog', { name: 'Full type for deployInfo' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(typeLabel, { exact: true })).toBeVisible();
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

test('struct values expand into semantic member rows', async ({ page }) => {
  const config = {
    ...scalarType('config', 'struct ConfigData'),
    kind: 'struct',
    num_bytes: '64',
    members: [
      {
        name: 'oracle',
        slot: '0x0',
        byte_offset: 0,
        byte_size: '20',
        type_id: 't_address',
        label: 'address',
      },
      {
        name: 'maxLTV',
        slot: '0x1',
        byte_offset: 0,
        byte_size: '32',
        type_id: 't_uint256',
        label: 'uint256',
      },
    ],
  };
  await mockView(page, {
    variables: [
      {
        ...variable('decl:0', 'config', '0x6', config.id, config.label),
        byte_size: config.num_bytes,
      },
    ],
    types: {
      config,
      t_address: scalarType('t_address', 'address', '20'),
      t_uint256: scalarType(),
    },
    values: [
      value('decl:0', 'config.oracle', '0x6', '0xff12b7B0dF9a2A96CBc09b3822B4Db43a575cCEE'),
      value('decl:0', 'config.maxLTV', '0x7', '95000'),
    ],
  });
  await page.goto(`/1/${ADDRESS}`);

  await expect(page.getByText('2 fields', { exact: true })).toBeVisible();
  await expect(page.getByText('oracle', { exact: true })).toHaveCount(0);

  const configRow = page.getByRole('row').filter({
    has: page.getByText('config', { exact: true }),
  });
  const configSlot = configRow.locator('td').nth(3);
  await expect(configSlot).toHaveText('6');
  await configSlot.locator('[aria-haspopup="dialog"]').focus();
  const slotDetail = page.getByRole('dialog', {
    name: 'Storage location: slots 0x6 through 0x7',
  });
  await expect(slotDetail.getByText('Slots', { exact: true })).toBeVisible();
  await expect(slotDetail.getByText('6–7', { exact: true })).toBeVisible();
  await expect(slotDetail.getByTestId('storage-slot-occupancy').locator('span')).toHaveCount(2);
  await page.keyboard.press('Escape');

  await page.getByRole('button', { name: 'Expand config' }).click();

  const oracleRow = page.getByRole('row').filter({
    has: page.getByText('oracle', { exact: true }),
  });
  await expect(oracleRow).toContainText('address');
  const oracleSlot = oracleRow.locator('td').nth(3);
  await expect(oracleSlot).toHaveText('6');
  await oracleSlot.locator('[aria-haspopup="dialog"]').focus();
  const byteDetail = page.getByRole('dialog', {
    name: 'Storage location: slot 0x6, bytes 0 through 19',
  });
  await expect(byteDetail.getByText('Bytes', { exact: true })).toBeVisible();
  await expect(byteDetail.getByText('0–19', { exact: true })).toBeVisible();
  await expect(byteDetail.getByTestId('storage-byte-occupancy').locator('span')).toHaveAttribute(
    'style',
    'left: 0%; width: 62.5%;',
  );
  await page.keyboard.press('Escape');
  await expect(oracleRow).toContainText('0xff12...cCEE');
  await oracleRow.getByTestId('compact-value').hover();
  await expect(page.getByRole('dialog')).toHaveText('0xff12b7B0dF9a2A96CBc09b3822B4Db43a575cCEE');
  await expect(oracleRow.locator('td').nth(4)).not.toContainText('config.oracle');

  const maxLtvRow = page.getByRole('row').filter({
    has: page.getByText('maxLTV', { exact: true }),
  });
  await expect(maxLtvRow).toContainText('uint256');
  await expect(maxLtvRow).toContainText('7');
  await expect(maxLtvRow).toContainText('95,000');

  await page.getByRole('button', { name: 'Collapse config' }).click();
  await expect(page.getByText('oracle', { exact: true })).toHaveCount(0);
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
    num_bytes: '64',
    members: [
      {
        name: 'limit',
        slot: '0x0',
        byte_offset: 0,
        byte_size: '32',
        type_id: 't_uint256',
        label: 'uint256',
      },
      {
        name: 'floor',
        slot: '0x1',
        byte_offset: 0,
        byte_size: '32',
        type_id: 't_uint256',
        label: 'uint256',
      },
    ],
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

test('packed struct mappings expand and render decoded members', async ({ page }) => {
  const deployInfo = {
    ...scalarType('deploy_info', 'struct DeployInfo'),
    kind: 'struct',
    members: [
      {
        name: 'protocolId',
        slot: '0x0',
        byte_offset: 0,
        byte_size: '5',
        type_id: 't_uint40',
        label: 'uint40',
      },
      {
        name: 'deployTime',
        slot: '0x0',
        byte_offset: 5,
        byte_size: '5',
        type_id: 't_uint40',
        label: 'uint40',
      },
    ],
  };
  const mapping = {
    ...scalarType('mapping', 'mapping(address => DeployInfo)'),
    kind: 'mapping',
    encoding: 'mapping',
    key_type: 't_address',
    value_type: deployInfo.id,
  };
  await mockView(page, {
    variables: [variable('decl:0', 'deployInfo', '0x4', mapping.id, mapping.label)],
    types: {
      mapping,
      deploy_info: deployInfo,
      t_address: scalarType('t_address', 'address', '20'),
      t_uint40: scalarType('t_uint40', 'uint40', '5'),
    },
    values: [value('decl:0', 'deployInfo', '0x4', null, 'on_demand')],
  });
  let requestBody: Record<string, any> | null = null;
  await page.route('**/api/slotscan/storage/query', async (route) => {
    requestBody = route.request().postDataJSON();
    await route.fulfill({
      json: {
        block_ref: { number: '0x7b', hash: BLOCK_HASH },
        layout_id: LAYOUT_ID,
        declaration_id: 'decl:0',
        path: `deployInfo[${ADDRESS}]`,
        type_id: deployInfo.id,
        type_label: deployInfo.label,
        location: { slot: '0xabc', byte_offset: 0, byte_size: 32 },
        array_length: null,
        storage: {
          regions: [
            { role: 'anchor', slot: '0x4', slot_count: '1' },
            { role: 'entry', slot: '0xabc', slot_count: '1' },
          ],
        },
        items: [
          {
            path: `deployInfo[${ADDRESS}].protocolId`,
            relative_path: 'protocolId',
            type_id: 't_uint40',
            type_label: 'uint40',
            location: { slot: '0xabc', byte_offset: 0, byte_size: 5 },
            value_encoded: `0x${'0'.repeat(44)}0066d210000000000007`,
            value_decoded: '7',
            storage: null,
          },
          {
            path: `deployInfo[${ADDRESS}].deployTime`,
            relative_path: 'deployTime',
            type_id: 't_uint40',
            type_label: 'uint40',
            location: { slot: '0xabc', byte_offset: 5, byte_size: 5 },
            value_encoded: `0x${'0'.repeat(44)}0066d210000000000007`,
            value_decoded: '1725000000',
            storage: null,
          },
        ],
      },
    });
  });
  await page.goto(`/1/${ADDRESS}`);

  await page.getByRole('button', { name: 'Expand deployInfo' }).click();
  await page.getByPlaceholder('Key').fill(ADDRESS);
  await page.getByRole('button', { name: 'Lookup' }).click();

  const result = page.getByTestId('lookup-result');
  const protocolRow = result.getByRole('row').filter({ hasText: 'protocolId' });
  await expect(protocolRow).toContainText('uint40');
  await expect(protocolRow).toContainText('0xabc');
  await expect(protocolRow).toContainText('7');
  const deployTimeRow = result.getByRole('row').filter({ hasText: 'deployTime' });
  await expect(deployTimeRow).toContainText('uint40');
  const deployTimeSlot = deployTimeRow.locator('td').nth(2);
  await expect(deployTimeSlot).toHaveText('0xabc');
  await deployTimeSlot.locator('[aria-haspopup="dialog"]').focus();
  const deployTimeSlotDetail = page.getByRole('dialog', {
    name: 'Storage location: slot 0xabc, bytes 5 through 9',
  });
  await expect(deployTimeSlotDetail.getByText('Bytes', { exact: true })).toBeVisible();
  await expect(deployTimeSlotDetail.getByText('5–9', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(deployTimeRow).toContainText('1,725,000,000');
  await expect(
    result.getByRole('button', { name: 'Copy deployInfo' }).first(),
  ).toBeVisible();
  expect(requestBody!.access.steps).toEqual([
    { kind: 'mapping_key', value: ADDRESS },
  ]);
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
        type_id: 't_uint256',
        type_label: 'uint256',
        location: { slot: '0xabc', byte_offset: 0, byte_size: 32 },
        array_length: null,
        storage: {
          regions: [
            { role: 'anchor', slot: '0x7', slot_count: '1' },
            { role: 'entry', slot: '0xabc', slot_count: '1' },
          ],
        },
        items: [{
          path: `balances[${ADDRESS}]`,
          relative_path: '',
          type_id: 't_uint256',
          type_label: 'uint256',
          location: { slot: '0xabc', byte_offset: 0, byte_size: 32 },
          value_encoded: `0x${'0'.repeat(63)}5`,
          value_decoded: '5',
          storage: {
            regions: [
              { role: 'anchor', slot: '0x7', slot_count: '1' },
              { role: 'entry', slot: '0xabc', slot_count: '1' },
            ],
          },
        }],
      },
    });
  });
  await page.goto(`/1/${ADDRESS}`);

  await page.getByRole('button', { name: 'Expand balances' }).click();
  await page.getByPlaceholder('Key').fill(ADDRESS);
  await page.getByRole('button', { name: 'Lookup' }).click();
  await expect(page.getByText('0xabc', { exact: true }).first()).toBeVisible();
  const keyCopy = page.getByRole('button', { name: 'Copy Key' });
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
  const voterType = scalarType('t_voter', 'address voter', '20');
  const proposalType = scalarType('t_proposal', 'uint256 proposalId');
  const outer = {
    id: 'outer',
    label: 'mapping(address => mapping(uint256 => uint256))',
    kind: 'mapping',
    encoding: 'mapping',
    num_bytes: '32',
    base_type: null,
    element_type: null,
    array_length: null,
    key_type: voterType.id,
    value_type: 'inner',
    members: [],
  };
  const inner = {
    ...outer,
    id: 'inner',
    label: 'mapping(uint256 => uint256)',
    key_type: proposalType.id,
    value_type: 't_uint256',
  };
  await mockView(page, {
    variables: [variable('decl:0', 'votes', '0x7', 'outer', outer.label)],
    types: {
      outer,
      inner,
      [voterType.id]: voterType,
      [proposalType.id]: proposalType,
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
        type_id: 't_uint256',
        type_label: 'uint256',
        location: { slot: '0xdef', byte_offset: 0, byte_size: 32 },
        array_length: null,
        storage: null,
        items: [{
          path: 'votes',
          relative_path: '',
          type_id: 't_uint256',
          type_label: 'uint256',
          location: { slot: '0xdef', byte_offset: 0, byte_size: 32 },
          value_encoded: `0x${'0'.repeat(63)}1`,
          value_decoded: '1',
          storage: null,
        }],
      },
    });
  });
  await page.goto(`/1/${ADDRESS}`);
  await page.getByRole('button', { name: 'Expand votes' }).click();
  await page.getByPlaceholder('0x… address').fill(ADDRESS);
  await page.getByPlaceholder('integer').fill('5');
  await expect(page.getByText('Key 1 · address', { exact: true })).toBeVisible();
  await expect(page.getByText('Key 2 · uint256', { exact: true })).toBeVisible();
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
          type_id: 't_uint32',
          type_label: 'uint32',
          location: { slot: '0xaaa', byte_offset: 12, byte_size: 4 },
          array_length: dynamic ? '4' : null,
          storage: dynamic
            ? {
                regions: [
                  { role: 'length', slot: '0x9', slot_count: '1' },
                  { role: 'entry', slot: '0xaaa', slot_count: '1' },
                ],
              }
            : null,
          items: [{
            path: 'items[3]',
            relative_path: '',
            type_id: 't_uint32',
            type_label: 'uint32',
            location: { slot: '0xaaa', byte_offset: 12, byte_size: 4 },
            value_encoded: `0x${'0'.repeat(63)}3`,
            value_decoded: '3',
            storage: dynamic
              ? {
                  regions: [
                    { role: 'length', slot: '0x9', slot_count: '1' },
                    { role: 'entry', slot: '0xaaa', slot_count: '1' },
                  ],
                }
              : null,
          }],
        },
      });
    });
    await page.goto(`/1/${ADDRESS}`);
    await page.getByRole('button', { name: 'Expand items' }).click();
    await page.getByPlaceholder(dynamic ? 'Array index' : 'Index (length 8)').fill('3');
    await page.getByRole('button', { name: 'Lookup' }).click();

    expect(requestBody!.access.steps).toEqual([{ kind: 'array_index', value: '3' }]);
    expect(requestBody!.block_ref).toEqual({ number: '0x7b', hash: BLOCK_HASH });
    expect(JSON.stringify(requestBody)).not.toContain('"slot"');
  });
}

test('proposalData indexes render a backend-authored multi-slot record', async ({ page }) => {
  const results = {
    ...scalarType('proposal_results', 'struct Voter.Vote'),
    kind: 'struct',
    members: [
      {
        name: 'weightYes',
        slot: '0x0',
        byte_offset: 0,
        byte_size: '5',
        type_id: 't_uint40',
        label: 'uint40',
      },
      {
        name: 'weightNo',
        slot: '0x0',
        byte_offset: 5,
        byte_size: '5',
        type_id: 't_uint40',
        label: 'uint40',
      },
    ],
  };
  const proposal = {
    ...scalarType('proposal', 'struct Voter.Proposal', '64'),
    kind: 'struct',
    members: [
      {
        name: 'epoch',
        slot: '0x0',
        byte_offset: 0,
        byte_size: '2',
        type_id: 't_uint16',
        label: 'uint16',
      },
      {
        name: 'createdAt',
        slot: '0x0',
        byte_offset: 2,
        byte_size: '4',
        type_id: 't_uint32',
        label: 'uint32',
      },
      {
        name: 'quorumWeight',
        slot: '0x0',
        byte_offset: 6,
        byte_size: '5',
        type_id: 't_uint40',
        label: 'uint40',
      },
      {
        name: 'processed',
        slot: '0x0',
        byte_offset: 11,
        byte_size: '1',
        type_id: 't_bool',
        label: 'bool',
      },
      {
        name: 'results',
        slot: '0x1',
        byte_offset: 0,
        byte_size: '32',
        type_id: results.id,
        label: results.label,
      },
    ],
  };
  const array = {
    ...scalarType('proposal_array', 'struct Voter.Proposal[]'),
    kind: 'array',
    encoding: 'dynamic_array',
    element_type: proposal.id,
  };
  await mockView(page, {
    variables: [
      variable('decl:0', 'proposalData', '0x1', array.id, array.label),
    ],
    types: {
      [array.id]: array,
      [proposal.id]: proposal,
      [results.id]: results,
      t_uint16: scalarType('t_uint16', 'uint16', '2'),
      t_uint32: scalarType('t_uint32', 'uint32', '4'),
      t_uint40: scalarType('t_uint40', 'uint40', '5'),
      t_bool: scalarType('t_bool', 'bool', '1'),
    },
    values: [value('decl:0', 'proposalData', '0x1', null, 'on_demand')],
  });
  let steps: unknown;
  const fields = [
    ['epoch', '0x1000', 0, 2, 'uint16', '15'],
    ['createdAt', '0x1000', 2, 4, 'uint32', '1751169587'],
    ['quorumWeight', '0x1000', 6, 5, 'uint40', '1486201'],
    ['processed', '0x1000', 11, 1, 'bool', true],
    ['results.weightYes', '0x1001', 0, 5, 'uint40', '3555667'],
    ['results.weightNo', '0x1001', 5, 5, 'uint40', '0'],
  ];
  await page.route('**/api/slotscan/storage/query', async (route) => {
    const request = route.request().postDataJSON();
    steps = request.access.steps;
    const queriedIndex = request.access.steps[0].value;
    await route.fulfill({
      json: {
        block_ref: { number: '0x7b', hash: BLOCK_HASH },
        layout_id: LAYOUT_ID,
        declaration_id: 'decl:0',
        path: `proposalData[${queriedIndex}]`,
        type_id: proposal.id,
        type_label: proposal.label,
        location: { slot: '0x1000', byte_offset: 0, byte_size: 64 },
        array_length: '26',
        storage: {
          regions: [
            { role: 'length', slot: '0x1', slot_count: '1' },
            { role: 'entry', slot: '0x1000', slot_count: '2' },
          ],
        },
        items: fields.map(([name, slot, byte_offset, byte_size, type_label, decoded]) => ({
          path: `proposalData[${queriedIndex}].${name}`,
          relative_path: name,
          type_id: `t_${type_label}`,
          type_label,
          location: { slot, byte_offset, byte_size },
          value_encoded: `0x${'0'.repeat(63)}1`,
          value_decoded: decoded,
          storage: null,
        })),
      },
    });
  });

  await page.goto(`/1/${ADDRESS}`);
  await page.getByRole('button', { name: 'Expand proposalData' }).click();
  const indexInput = page.getByPlaceholder('Array index');
  await indexInput.fill('0');
  await page.getByRole('button', { name: 'Lookup' }).click();

  expect(steps).toEqual([{ kind: 'array_index', value: '0' }]);
  await expect(indexInput).toHaveValue('0');
  const result = page.getByTestId('lookup-result');
  await expect(result.locator('tbody > tr')).toHaveCount(7);
  await expect(result.locator('tbody > tr').first().locator('td').first()).toHaveText('[0]');
  await expect(result.getByText('6 fields')).toBeVisible();
  await expect(result.getByRole('row').filter({ hasText: 'processed' })).toContainText('true');
  const parentRow = result.getByRole('row').filter({ hasText: '6 fields' });
  await parentRow.locator('td').nth(2).locator('[aria-haspopup="dialog"]').focus();
  const detail = page.getByRole('dialog', {
    name: 'Storage location: length 0x1, entry 0x1000–0x1001',
  });
  await expect(detail.getByText('length', { exact: true })).toBeVisible();
  await expect(detail.getByText('entry', { exact: true })).toBeVisible();
  await expect(
    detail.getByTestId('storage-computed-occupancy').locator('span'),
  ).toHaveCount(2);
  await expect(detail.getByTestId('storage-slot-occupancy')).toHaveCount(0);

  await indexInput.fill('1');
  await page.getByRole('button', { name: 'Lookup' }).click();
  await expect(indexInput).toHaveValue('1');
  await expect(result.locator('tbody > tr')).toHaveCount(7);
  await expect(result.locator('tbody > tr').first().locator('td').first()).toHaveText('[1]');

  await result.getByRole('button', { name: 'Dismiss result' }).click();
  await expect(result).toHaveCount(0);
  await expect(indexInput).toHaveValue('1');
});

test('proposalDescription keys render long string data provenance', async ({ page }) => {
  const string = {
    ...scalarType('t_string_storage', 'string'),
    encoding: 'bytes',
  };
  const mapping = {
    ...scalarType('description_mapping', 'mapping(uint256 => string)'),
    kind: 'mapping',
    encoding: 'mapping',
    key_type: 't_uint256',
    value_type: string.id,
  };
  await mockView(page, {
    variables: [
      variable(
        'decl:0',
        'proposalDescription',
        '0x3',
        mapping.id,
        mapping.label,
      ),
    ],
    types: {
      [mapping.id]: mapping,
      [string.id]: string,
      t_uint256: scalarType(),
    },
    values: [
      value('decl:0', 'proposalDescription', '0x3', null, 'on_demand'),
    ],
  });
  await page.route('**/api/slotscan/storage/query', async (route) => {
    await route.fulfill({
      json: {
        block_ref: { number: '0x7b', hash: BLOCK_HASH },
        layout_id: LAYOUT_ID,
        declaration_id: 'decl:0',
        path: 'proposalDescription[0]',
        type_id: string.id,
        type_label: string.label,
        location: { slot: '0x2000', byte_offset: 0, byte_size: 32 },
        array_length: null,
        storage: {
          regions: [
            { role: 'anchor', slot: '0x3', slot_count: '1' },
            { role: 'length', slot: '0x2000', slot_count: '1' },
            { role: 'data', slot: '0x3000', slot_count: '2' },
          ],
        },
        items: [{
          path: 'proposalDescription[0]',
          relative_path: '',
          type_id: string.id,
          type_label: string.label,
          location: { slot: '0x2000', byte_offset: 0, byte_size: 32 },
          value_encoded: `0x${'0'.repeat(63)}5`,
          value_decoded: 'Pay bad debt through governance with a long explanation',
          storage: {
            regions: [
              { role: 'anchor', slot: '0x3', slot_count: '1' },
              { role: 'length', slot: '0x2000', slot_count: '1' },
              { role: 'data', slot: '0x3000', slot_count: '2' },
            ],
          },
        }],
      },
    });
  });

  await page.goto(`/1/${ADDRESS}`);
  await page.getByRole('button', { name: 'Expand proposalDescription' }).click();
  await page.getByPlaceholder('Key').fill('0');
  await page.getByRole('button', { name: 'Lookup' }).click();

  const result = page.getByTestId('lookup-result');
  const resultRow = result.getByRole('row').filter({
    hasText: 'Pay bad debt',
  });
  await expect(resultRow).toContainText('string');
  await resultRow.locator('td').nth(2).locator('[aria-haspopup="dialog"]').focus();
  const detail = page.getByRole('dialog', {
    name: 'Storage location: anchor 0x3, length 0x2000, data 0x3000–0x3001',
  });
  await expect(detail.getByText('anchor', { exact: true })).toBeVisible();
  await expect(detail.getByText('data', { exact: true })).toBeVisible();
});

test('proposalPayload uses one ordered Key to Index access flow', async ({ page }) => {
  const bytes = {
    ...scalarType('t_bytes_storage', 'bytes'),
    encoding: 'bytes',
  };
  const action = {
    ...scalarType('action', 'struct Voter.Action', '64'),
    kind: 'struct',
    members: [
      {
        name: 'target',
        slot: '0x0',
        byte_offset: 0,
        byte_size: '20',
        type_id: 't_address',
        label: 'address',
      },
      {
        name: 'data',
        slot: '0x1',
        byte_offset: 0,
        byte_size: '32',
        type_id: bytes.id,
        label: 'bytes',
      },
    ],
  };
  const actions = {
    ...scalarType('actions', 'struct Voter.Action[]'),
    kind: 'array',
    encoding: 'dynamic_array',
    element_type: action.id,
  };
  const mapping = {
    ...scalarType(
      'payload_mapping',
      'mapping(uint256 => struct Voter.Action[])',
    ),
    kind: 'mapping',
    encoding: 'mapping',
    key_type: 't_uint256',
    value_type: actions.id,
  };
  await mockView(page, {
    variables: [
      variable('decl:0', 'proposalPayload', '0x2', mapping.id, mapping.label),
    ],
    types: {
      [mapping.id]: mapping,
      [actions.id]: actions,
      [action.id]: action,
      [bytes.id]: bytes,
      t_uint256: scalarType(),
      t_address: scalarType('t_address', 'address', '20'),
    },
    values: [value('decl:0', 'proposalPayload', '0x2', null, 'on_demand')],
  });
  let steps: unknown;
  await page.route('**/api/slotscan/storage/query', async (route) => {
    steps = route.request().postDataJSON().access.steps;
    await route.fulfill({
      json: {
        block_ref: { number: '0x7b', hash: BLOCK_HASH },
        layout_id: LAYOUT_ID,
        declaration_id: 'decl:0',
        path: 'proposalPayload[0][0]',
        type_id: action.id,
        type_label: action.label,
        location: { slot: '0x4000', byte_offset: 0, byte_size: 64 },
        array_length: '9',
        storage: {
          regions: [
            { role: 'anchor', slot: '0x2', slot_count: '1' },
            { role: 'length', slot: '0x3500', slot_count: '1' },
            { role: 'entry', slot: '0x4000', slot_count: '2' },
          ],
        },
        items: [
          {
            path: 'proposalPayload[0][0].target',
            relative_path: 'target',
            type_id: 't_address',
            type_label: 'address',
            location: { slot: '0x4000', byte_offset: 0, byte_size: 20 },
            value_encoded: `0x${'0'.repeat(24)}${ADDRESS.slice(2)}`,
            value_decoded: ADDRESS,
            storage: null,
          },
          {
            path: 'proposalPayload[0][0].data',
            relative_path: 'data',
            type_id: bytes.id,
            type_label: bytes.label,
            location: { slot: '0x4001', byte_offset: 0, byte_size: 32 },
            value_encoded: `0x${'0'.repeat(63)}5`,
            value_decoded: `0x${'12'.repeat(36)}`,
            storage: {
              regions: [
                { role: 'length', slot: '0x4001', slot_count: '1' },
                { role: 'data', slot: '0x5000', slot_count: '2' },
              ],
            },
          },
        ],
      },
    });
  });

  await page.goto(`/1/${ADDRESS}`);
  await page.getByRole('button', { name: 'Expand proposalPayload' }).click();
  await page.getByPlaceholder('Key').fill('0');
  await page.getByPlaceholder('Array index').fill('0');
  await expect(page.getByText('Key · uint256', { exact: true })).toBeVisible();
  await expect(page.getByText('Index · index', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Lookup' }).click();

  expect(steps).toEqual([
    { kind: 'mapping_key', value: '0' },
    { kind: 'array_index', value: '0' },
  ]);
  const result = page.getByTestId('lookup-result');
  await expect(result.getByRole('row').filter({ hasText: 'target' })).toContainText('0x1234...5678');
  await expect(result.getByRole('row').filter({ hasText: 'data' })).toContainText('0x121212');
});

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
  await page.getByPlaceholder('Array index').fill('-1');
  await page.getByRole('button', { name: 'Lookup' }).click();

  await expect(page.getByText('Enter a non-negative decimal or hexadecimal index')).toBeVisible();
  expect(queryCount).toBe(0);
});
