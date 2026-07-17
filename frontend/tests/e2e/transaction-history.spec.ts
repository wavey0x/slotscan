import { expect, test } from '@playwright/test';

const SIMPLE_TX = '0x711899730951bad9b5b29d16c0ffd0be3a7aefcd96b9e1d376619f02bdd9c1d3';
const RESTORED_TX = '0x7fe79d06862f71a5809babfadac1c9a204b09dfbb8c40ac725d23b9bae2b7cac';
const REVERTED_WRITES_TX = '0x561dd631cb9eabc2ba595ca4410fd26ca3e6183d2b8ba4f55bbf4c4b9c742ae2';
const SOURCE_LAYOUT_TX = '0x3353c2009d984e15a2dd909d09f56f2833cfa99129fa834ea6eaf9349f14cd60';
const NESTED_STRUCT_MAPPING_TX = '0x8e37bdd5003c883a684cd6c944c5fac24cc7f29b15ef23c5f6d7adf41c222f82';
const GNOSIS_SAFE_ADDRESS = '0x16388463d60ffe0661cf7f1f31a7d658ac790ff7';
const LIDO_ADDRESS = '0xae7ab96520de3a18e5e111b5eaab095312d7fe84';
const TETHER_ADDRESS = '0xdac17f958d2ee523a2206206994597c13d831ec7';
const RESOLUTION_TX = `0x${'12'.repeat(32)}`;
const RESOLUTION_FROM = '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
const RESOLUTION_TO = '0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

function resolutionContract(overrides: Record<string, unknown>) {
  return {
    storage_address: '0x1111111111111111111111111111111111111111',
    name: null,
    is_proxy: false,
    is_verified: false,
    implementation_addresses: [],
    code_addresses: ['0x1111111111111111111111111111111111111111'],
    first_write_step: 1,
    last_write_step: 1,
    layout_available: false,
    resolution_status: 'resolved',
    resolution: { resolved: 0, total: 1 },
    counts: {
      slots_written: 1,
      sstore_events: 1,
      net_changed_slots: 1,
      restored_slots: 0,
      reverted_only_slots: 0,
      noop_only_slots: 0,
      reverted_writes: 0,
      noop_writes: 0,
    },
    errors: [],
    slots: [],
    ...overrides,
  };
}

function resolutionResponse(contracts: ReturnType<typeof resolutionContract>[]) {
  return {
    chain_id: 1,
    tx_hash: RESOLUTION_TX,
    block_number: 1,
    status: 'success',
    from_address: RESOLUTION_FROM,
    to_address: RESOLUTION_TO,
    created_contract: null,
    analysis_version: 5,
    capabilities: {
      write_history_complete: true,
      values_complete: true,
      rollback_classification_complete: true,
      execution_order_available: true,
      final_state_values_available: true,
      state_reconciliation_complete: true,
      address_attribution_complete: true,
      code_attribution_complete: true,
    },
    summary: {
      storage_owners: contracts.length,
      slots_written: contracts.length,
      sstore_events: contracts.length,
      net_changed_slots: contracts.length,
      restored_slots: 0,
      reverted_only_slots: 0,
      noop_only_slots: 0,
      reverted_writes: 0,
      noop_writes: 0,
      resolved_slots: 0,
    },
    contracts,
    global_order: [],
    is_complete: true,
    trace_unavailable: false,
  };
}

function structuredValueSlot() {
  const before = {
    value_encoded: `0x${'00'.repeat(32)}`,
    value_decoded: {
      duration: '157680000',
      amount: '9999999999999999960000000',
      claimed: '0',
    },
  };
  const after = {
    value_encoded: `0x${'01'.repeat(32)}`,
    value_decoded: {
      duration: '157680000',
      amount: '9999999999999999960000000',
      claimed: '2000000000000000000',
    },
  };

  return {
    slot: `0x${'6d'.repeat(32)}`,
    slot_decimal: '49344',
    is_static_slot: false,
    provenance: 'trace',
    confidence: 'exact',
    namespace: 'persistent',
    net_changed: true,
    classification: 'net_changed',
    first_write_step: 1044,
    last_write_step: 1044,
    event_count: 1,
    state_values_known: true,
    variable_name: 'userVests',
    variable_path: 'userVests[0x12340000000000000000000000000000000000e8]',
    resolved_paths: [],
    type_label: 'Vest',
    params: [{ type: 'address', value: '0x12340000000000000000000000000000000000e8', label: null }],
    mapping_base_slot: 6,
    is_mapping: true,
    is_dynamic_array: false,
    array_index: null,
    encoding: 'mapping',
    value_type: 'Vest',
    before,
    after,
    packed_fields: null,
    struct_field: null,
    struct_definition: null,
    changes: [{
      before,
      after,
      pc: 1,
      step: 1044,
      effect: 'applied',
      storage_address: '0x6666666666666666666666666666666666666666',
      code_address: '0x6666666666666666666666666666666666666666',
      changed_value: true,
      frame_outcome: 'applied',
      frame_id: 1,
      depth: 1,
      opcode: 'SSTORE',
      namespace: 'persistent',
    }],
  };
}

function configStructSlot({
  slot,
  member,
  typeLabel,
  beforeValue,
  afterValue,
  beforeEncoded,
  afterEncoded,
  step,
}: {
  slot: number;
  member: string;
  typeLabel: string;
  beforeValue: unknown;
  afterValue: unknown;
  beforeEncoded: string;
  afterEncoded: string;
  step: number;
}) {
  const before = { value_encoded: beforeEncoded, value_decoded: { [member]: beforeValue } };
  const after = { value_encoded: afterEncoded, value_decoded: { [member]: afterValue } };
  const changed = beforeEncoded !== afterEncoded;

  return {
    slot: `0x${slot.toString(16).padStart(64, '0')}`,
    slot_decimal: slot.toString(),
    is_static_slot: true,
    provenance: 'compiler_layout',
    confidence: 'exact',
    namespace: 'persistent',
    net_changed: changed,
    classification: changed ? 'net_changed' : 'noop_only',
    first_write_step: step,
    last_write_step: step,
    event_count: 1,
    state_values_known: true,
    variable_name: '_defaultConfigData',
    variable_path: '_defaultConfigData',
    resolved_paths: [],
    type_label: 'ConfigData',
    params: null,
    mapping_base_slot: null,
    is_mapping: false,
    is_dynamic_array: false,
    array_index: null,
    encoding: 'inplace',
    value_type: null,
    before,
    after,
    packed_fields: [{
      name: member,
      type_label: typeLabel,
      offset: 0,
      size: 32,
      before: { value_decoded: beforeValue },
      after: { value_decoded: afterValue },
    }],
    struct_field: null,
    struct_definition: {
      name: 'ConfigData',
      members: [{ name: member, type_label: typeLabel, slot_offset: slot - 6, byte_offset: 0, size: 32 }],
    },
    changes: [{
      before,
      after,
      pc: 1,
      step,
      effect: changed ? 'applied' : 'noop',
      storage_address: '0x6666666666666666666666666666666666666666',
      code_address: '0x6666666666666666666666666666666666666666',
      changed_value: changed,
      frame_outcome: 'applied',
      frame_id: 1,
      depth: 1,
      opcode: 'SSTORE',
      namespace: 'persistent',
    }],
  };
}

function configScalarSlot({
  slot,
  variable,
  typeLabel,
  beforeValue,
  afterValue,
  beforeEncoded,
  afterEncoded,
  step,
}: {
  slot: number;
  variable: string;
  typeLabel: string;
  beforeValue: unknown;
  afterValue: unknown;
  beforeEncoded: string;
  afterEncoded: string;
  step: number;
}) {
  const base = configStructSlot({
    slot,
    member: variable,
    typeLabel,
    beforeValue,
    afterValue,
    beforeEncoded,
    afterEncoded,
    step,
  });
  const before = { value_encoded: beforeEncoded, value_decoded: beforeValue };
  const after = { value_encoded: afterEncoded, value_decoded: afterValue };

  return {
    ...base,
    variable_name: variable,
    variable_path: variable,
    type_label: typeLabel,
    before,
    after,
    packed_fields: null,
    struct_definition: null,
    changes: base.changes.map((change) => ({ ...change, before, after })),
  };
}

function packedStructSlot() {
  const base = configStructSlot({
    slot: 10,
    member: 'anchor',
    typeLabel: 'uint128',
    beforeValue: '1',
    afterValue: '2',
    beforeEncoded: `0x${'00'.repeat(31)}01`,
    afterEncoded: `0x${'00'.repeat(31)}02`,
    step: 1500,
  });
  const before = {
    ...base.before,
    value_decoded: {
      rounded: '1234500000000000',
      anchor: '1',
    },
  };
  const after = {
    ...base.after,
    value_decoded: {
      rounded: '1234599999999999',
      anchor: '2',
    },
  };

  return {
    ...base,
    variable_name: 'packedData',
    variable_path: 'packedData',
    before,
    after,
    packed_fields: [
      {
        name: 'rounded',
        type_label: 'uint128',
        offset: 0,
        size: 16,
        before: { value_decoded: before.value_decoded.rounded },
        after: { value_decoded: after.value_decoded.rounded },
      },
      {
        name: 'anchor',
        type_label: 'uint128',
        offset: 16,
        size: 16,
        before: { value_decoded: before.value_decoded.anchor },
        after: { value_decoded: after.value_decoded.anchor },
      },
    ],
    struct_definition: {
      name: 'PackedData',
      members: [
        { name: 'rounded', type_label: 'uint128', slot_offset: 0, byte_offset: 0, size: 16 },
        { name: 'anchor', type_label: 'uint128', slot_offset: 0, byte_offset: 16, size: 16 },
      ],
    },
    changes: base.changes.map((change) => ({ ...change, before, after })),
  };
}

function packedMappingStructSlot({ index, changeBoth = false }: { index: number; changeBoth?: boolean }) {
  const step = 1600 + index;
  const base = configStructSlot({
    slot: index,
    member: 'processed',
    typeLabel: 'bool',
    beforeValue: false,
    afterValue: true,
    beforeEncoded: `0x${'00'.repeat(32)}`,
    afterEncoded: `0x${'00'.repeat(31)}01`,
    step,
  });
  const before = {
    ...base.before,
    value_decoded: { processed: false, quorum: 3 },
  };
  const after = {
    ...base.after,
    value_decoded: { processed: true, quorum: changeBoth ? 4 : 3 },
  };
  const slotByte = index === 20 ? 'b1' : 'b2';

  return {
    ...base,
    slot: `0x${slotByte.repeat(32)}`,
    slot_decimal: null,
    is_static_slot: false,
    provenance: 'trace',
    variable_name: 'proposalData',
    variable_path: `proposalData[${index}]`,
    type_label: 'packed',
    params: [{ type: 'uint256', value: String(index), label: null }],
    mapping_base_slot: 4,
    is_mapping: true,
    encoding: 'mapping',
    value_type: 'packed',
    before,
    after,
    packed_fields: [
      {
        ...base.packed_fields[0],
        size: 1,
        before: { value_decoded: false },
        after: { value_decoded: true },
      },
      {
        name: 'quorum',
        type_label: 'uint16',
        offset: 1,
        size: 2,
        before: { value_decoded: 3 },
        after: { value_decoded: changeBoth ? 4 : 3 },
      },
    ],
    struct_field: null,
    struct_definition: {
      name: 'ProposalData',
      members: [
        { ...base.struct_definition.members[0], size: 1 },
        { name: 'quorum', type_label: 'uint16', slot_offset: 0, byte_offset: 1, size: 2 },
      ],
    },
    changes: base.changes.map((change) => ({ ...change, before, after })),
  };
}

test('home search accepts a transaction hash and opens transaction-wide history', async ({ page }) => {
  await page.goto('/');
  await page.getByPlaceholder('Contract address or transaction hash (0x...)').fill(SIMPLE_TX);
  await page.getByRole('button', { name: 'Analyze Storage' }).click();

  await expect(page).toHaveURL(`/1/tx/${SIMPLE_TX}`);
  await expect(page.getByRole('heading', { name: '0x711899...d9c1d3' })).toBeVisible();
  await expect(page.getByText('Transaction storage history', { exact: true })).toHaveCount(0);
  await expect(page.getByTestId('summary-writes').getByText('2', { exact: true })).toBeVisible();
  await expect(page.getByTestId('summary-slots').getByText('2', { exact: true })).toBeVisible();
  for (const label of ['Block', 'From', 'To']) {
    await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
  }
  await expect(page.getByRole('button', { name: 'Grouped' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: 'Decoded' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('link', { name: '0x711899...d9c1d3' })).toBeVisible();
  const tetherSection = page.getByRole('heading', { name: 'TetherToken' }).locator('xpath=ancestor::section');
  await expect(tetherSection.getByRole('link', { name: '0xdac1...1ec7' })).toHaveAttribute('href', `/1/${TETHER_ADDRESS}`);
  await expect(tetherSection.getByRole('link', { name: 'View contract on Etherscan' })).toHaveAttribute('href', `https://etherscan.io/address/${TETHER_ADDRESS}`);
  await expect(tetherSection.getByRole('link', { name: 'View contract on Etherscan' })).toHaveAttribute('target', '_blank');
  await expect(page.getByRole('checkbox')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Net effects' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Restored' })).toHaveCount(0);
});

test('unnamed contracts distinguish layout, source, and raw-slot states', async ({ page }) => {
  const contracts = [
    resolutionContract({
      storage_address: '0x1111111111111111111111111111111111111111',
      code_addresses: ['0x1111111111111111111111111111111111111111'],
      layout_available: true,
      resolution_status: 'resolved',
    }),
    resolutionContract({
      storage_address: '0x2222222222222222222222222222222222222222',
      code_addresses: ['0x2222222222222222222222222222222222222222'],
      resolution_status: 'no_verified_source',
    }),
    resolutionContract({
      storage_address: '0x3333333333333333333333333333333333333333',
      code_addresses: ['0x3333333333333333333333333333333333333333'],
      is_verified: true,
      resolution_status: 'resolved',
    }),
    resolutionContract({
      storage_address: '0x4444444444444444444444444444444444444444',
      code_addresses: ['0x4444444444444444444444444444444444444444'],
      name: 'NamedWithoutLayout',
      is_verified: true,
      resolution_status: 'resolved',
    }),
  ];
  await page.route(`**/api/slotscan/tx/1/${RESOLUTION_TX}*`, async (route) => {
    await route.fulfill({ json: resolutionResponse(contracts) });
  });

  await page.goto(`/1/tx/${RESOLUTION_TX}`);

  const unnamed = page.getByRole('heading', { name: 'Unnamed contract' }).locator('xpath=ancestor::section');
  await expect(unnamed.getByText('layout available', { exact: true })).toBeVisible();
  const noSource = page.getByRole('heading', { name: 'No verified source' }).locator('xpath=ancestor::section');
  await expect(noSource.getByText('raw slots', { exact: true })).toBeVisible();
  const noLayout = page.getByRole('heading', { name: 'Verified source, no layout' }).locator('xpath=ancestor::section');
  await expect(noLayout.getByText('layout unavailable · raw slots', { exact: true })).toBeVisible();
  const named = page.getByRole('heading', { name: 'NamedWithoutLayout' }).locator('xpath=ancestor::section');
  await expect(named.getByText('layout unavailable · raw slots', { exact: true })).toBeVisible();
  await expect(page.getByText('Unresolved contract', { exact: true })).toHaveCount(0);
});

test('structured values show only changed fields without spilling', async ({ page }) => {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  const contract = resolutionContract({
    storage_address: '0x6666666666666666666666666666666666666666',
    code_addresses: ['0x6666666666666666666666666666666666666666'],
    name: 'VestManager',
    is_verified: true,
    layout_available: true,
    resolution: { resolved: 1, total: 1 },
    slots: [structuredValueSlot()],
  });
  await page.route(`**/api/slotscan/tx/1/${RESOLUTION_TX}*`, async (route) => {
    await route.fulfill({ json: resolutionResponse([contract]) });
  });

  await page.goto(`/1/tx/${RESOLUTION_TX}`);
  await page.getByTestId('contract-toggle').click();

  const diff = page.getByTestId('structured-value-diff');
  await expect(diff).toBeVisible();
  await expect(diff.getByText('claimed', { exact: true })).toBeVisible();
  await expect(diff.getByText('duration', { exact: true })).toHaveCount(0);
  await expect(diff.getByText('amount', { exact: true })).toHaveCount(0);
  await expect(diff).toContainText('2e18');
  expect(await diff.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  const beforeBox = await diff.getByTestId('value-before').boundingBox();
  const afterBox = await diff.getByTestId('value-after').boundingBox();
  expect(beforeBox).not.toBeNull();
  expect(afterBox).not.toBeNull();
  expect(Math.abs(beforeBox!.x - afterBox!.x)).toBeLessThan(1);
  expect(afterBox!.y).toBeGreaterThan(beforeBox!.y);

  await diff.getByRole('button', { name: 'Copy new claimed' }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('2000000000000000000');
});

test('packed change detection uses full values rather than compact display text', async ({ page }) => {
  const contract = resolutionContract({
    storage_address: '0x6666666666666666666666666666666666666666',
    code_addresses: ['0x6666666666666666666666666666666666666666'],
    name: 'PackedValues',
    is_verified: true,
    layout_available: true,
    slots: [packedStructSlot()],
  });
  await page.route(`**/api/slotscan/tx/1/${RESOLUTION_TX}*`, async (route) => {
    await route.fulfill({ json: resolutionResponse([contract]) });
  });

  await page.goto(`/1/tx/${RESOLUTION_TX}`);
  await page.getByTestId('contract-toggle').click();

  const roundedRow = page.getByText('rounded', { exact: true }).locator('xpath=ancestor::tr');
  await expect(roundedRow.getByTestId('value-before')).toContainText('1.2345e15');
  await expect(roundedRow.getByTestId('value-after')).toContainText('1.2345e15');
  await expect(roundedRow.getByTestId('value-arrow')).toBeVisible();
  await expect(page.getByText('anchor', { exact: true })).toBeVisible();
});

test('timeline promotes one packed member into a compact canonical mobile path', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  const singleMemberSlot = packedMappingStructSlot({ index: 20 });
  const multiMemberSlot = packedMappingStructSlot({ index: 21, changeBoth: true });
  const contract = resolutionContract({
    storage_address: '0x6666666666666666666666666666666666666666',
    code_addresses: ['0x6666666666666666666666666666666666666666'],
    name: 'Voter',
    is_verified: true,
    layout_available: true,
    counts: {
      slots_written: 2,
      sstore_events: 2,
      net_changed_slots: 2,
      restored_slots: 0,
      reverted_only_slots: 0,
      noop_only_slots: 0,
      reverted_writes: 0,
      noop_writes: 0,
    },
    slots: [singleMemberSlot, multiMemberSlot],
  });
  const response = resolutionResponse([
    contract,
    resolutionContract({
      storage_address: '0x7777777777777777777777777777777777777777',
      code_addresses: ['0x7777777777777777777777777777777777777777'],
      name: 'OtherContract',
    }),
  ]);
  response.global_order = [singleMemberSlot, multiMemberSlot].map((slot, ordinal) => ({
    ordinal,
    step: slot.changes[0].step,
    storage_address: contract.storage_address,
    slot: slot.slot,
    event_index: 0,
  }));
  await page.route(`**/api/slotscan/tx/1/${RESOLUTION_TX}*`, async (route) => {
    await route.fulfill({ json: response });
  });

  await page.goto(`/1/tx/${RESOLUTION_TX}?view=timeline`);

  const singleRow = page.getByTestId('timeline-event').filter({ hasText: 'proposalData[20].processed' });
  const canonicalPath = singleRow.getByTestId('keyed-variable-primary');
  await expect(canonicalPath).toHaveText('proposalData[20].processed');
  await expect(canonicalPath.getByTestId('keyed-variable-base')).toHaveText('proposalData');
  await expect(canonicalPath.getByTestId('keyed-variable-leaf')).toHaveText('.processed');
  expect(await canonicalPath.getByTestId('keyed-variable-base').evaluate(
    (element) => element.clientWidth,
  )).toBeGreaterThanOrEqual(24);
  await expect(singleRow.getByTestId('keyed-variable-context')).toHaveCount(0);
  await expect(singleRow.getByTestId('timeline-value')).not.toContainText('processed');
  await expect(singleRow.getByTestId('timeline-value')).toContainText('false');
  await expect(singleRow.getByTestId('timeline-value')).toContainText('true');
  const slotReference = singleRow.getByTestId('slot-reference');
  const slotDisplay = slotReference.getByText('0xb1..b1', { exact: true });
  await expect(slotDisplay).toBeVisible();
  expect(await slotDisplay.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  const slotMetrics = await slotReference.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(slotMetrics.scrollWidth).toBeLessThanOrEqual(slotMetrics.clientWidth);

  await canonicalPath.click();
  const pathDetail = page.getByRole('dialog');
  await expect(pathDetail).toContainText('proposalData[20].processed');
  await pathDetail.getByRole('button', { name: 'Copy full path' }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(
    'proposalData[20].processed',
  );

  const multiRow = page.getByTestId('timeline-event').filter({ hasText: 'proposalData[21]' });
  await expect(multiRow.getByTestId('keyed-variable-leaf')).toHaveCount(0);
  await expect(multiRow.getByTestId('timeline-value')).toContainText('processed');
  await expect(multiRow.getByTestId('timeline-value')).toContainText('quorum');

  const singleBox = await singleRow.boundingBox();
  const multiBox = await multiRow.boundingBox();
  expect(singleBox).not.toBeNull();
  expect(multiBox).not.toBeNull();
  expect(singleBox!.height).toBeLessThan(multiBox!.height);
  const scroll = page.getByTestId('data-table-scroll');
  expect(await scroll.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
});

test('timeline names struct members and stays readable on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const oldRate = '0x1972B5D65A690De0BC36278AC93D47fd98Bc14f7';
  const newRate = '0xD3d5C6fc52f3bc29C3aB017d57D9A94A036Ca90f';
  const oracle = '0xa346BA5E838D6Ee40204A69549c81AB982644150';
  const oracleEncoded = `0x${'0'.repeat(24)}${oracle.slice(2).toLowerCase()}`;
  const oldRateEncoded = `0x${'0'.repeat(24)}${oldRate.slice(2).toLowerCase()}`;
  const newRateEncoded = `0x${'0'.repeat(24)}${newRate.slice(2).toLowerCase()}`;
  const slots = [
    configStructSlot({
      slot: 6,
      member: 'oracle',
      typeLabel: 'address',
      beforeValue: oracle,
      afterValue: oracle,
      beforeEncoded: oracleEncoded,
      afterEncoded: oracleEncoded,
      step: 1414,
    }),
    configStructSlot({
      slot: 7,
      member: 'rateCalculator',
      typeLabel: 'address',
      beforeValue: oldRate,
      afterValue: newRate,
      beforeEncoded: oldRateEncoded,
      afterEncoded: newRateEncoded,
      step: 1425,
    }),
    configStructSlot({
      slot: 8,
      member: 'processed',
      typeLabel: 'bool',
      beforeValue: true,
      afterValue: false,
      beforeEncoded: `0x${'0'.repeat(63)}1`,
      afterEncoded: `0x${'0'.repeat(64)}`,
      step: 1429,
    }),
    configScalarSlot({
      slot: 9,
      variable: '_status',
      typeLabel: 'uint8',
      beforeValue: 1,
      afterValue: 2,
      beforeEncoded: `0x${'0'.repeat(63)}1`,
      afterEncoded: `0x${'0'.repeat(63)}2`,
      step: 1431,
    }),
  ];
  const contract = resolutionContract({
    storage_address: '0x6666666666666666666666666666666666666666',
    code_addresses: ['0x6666666666666666666666666666666666666666'],
    name: 'ResupplyPairDeployer',
    is_verified: true,
    layout_available: true,
    counts: {
      slots_written: 4,
      sstore_events: 4,
      net_changed_slots: 3,
      restored_slots: 0,
      reverted_only_slots: 0,
      noop_only_slots: 1,
      reverted_writes: 0,
      noop_writes: 1,
    },
    slots,
  });
  const response = resolutionResponse([
    contract,
    resolutionContract({
      storage_address: '0x7777777777777777777777777777777777777777',
      code_addresses: ['0x7777777777777777777777777777777777777777'],
      name: 'OtherContract',
    }),
  ]);
  response.global_order = slots.map((slot, ordinal) => ({
    ordinal,
    step: slot.changes[0].step,
    storage_address: contract.storage_address,
    slot: slot.slot,
    event_index: 0,
  }));
  await page.route(`**/api/slotscan/tx/1/${RESOLUTION_TX}*`, async (route) => {
    await route.fulfill({ json: response });
  });

  await page.goto(`/1/tx/${RESOLUTION_TX}?view=timeline`);

  const truncatedOracle = `${oracle.slice(0, 6)}...${oracle.slice(-4)}`;
  const truncatedOldRate = `${oldRate.slice(0, 6)}...${oldRate.slice(-4)}`;
  const truncatedNewRate = `${newRate.slice(0, 6)}...${newRate.slice(-4)}`;
  const noopRow = page.getByTestId('timeline-event').filter({ hasText: '_defaultConfigData.oracle' });
  const changedRow = page.getByTestId('timeline-event').filter({ hasText: '_defaultConfigData.rateCalculator' });
  const booleanRow = page.getByTestId('timeline-event').filter({ hasText: '_defaultConfigData.processed' });
  const smallNumberRow = page.getByTestId('timeline-event').filter({ hasText: '_status' });

  // No-op writes show the value once with an unchanged indicator, not an arrow.
  await expect(noopRow.getByTestId('timeline-value')).toContainText(truncatedOracle);
  const noopIndicator = noopRow.getByTestId('value-noop-indicator');
  await expect(noopIndicator).toBeVisible();
  await expect(noopIndicator).toHaveText('=');
  await expect(noopIndicator).not.toHaveAttribute('title', /.+/);
  await expect(noopIndicator.locator('svg')).toHaveCount(0);
  await noopIndicator.hover();
  await expect(page.getByRole('dialog', { name: 'Same value written' })).toContainText('Same value written');
  await changedRow.hover();
  await expect(page.getByRole('dialog', { name: 'Same value written' })).toHaveCount(0);
  await expect(noopRow.getByTestId('value-arrow')).toHaveCount(0);
  await expect(noopRow.getByRole('button', { name: 'Copy oracle' })).toBeVisible();
  await expect(noopRow.getByRole('button', { name: 'Copy previous oracle' })).toHaveCount(0);

  // Addresses middle-truncate in value cells; copy actions keep full values.
  await expect(changedRow.getByTestId('timeline-value')).toContainText(truncatedOldRate);
  await expect(changedRow.getByTestId('timeline-value')).toContainText(truncatedNewRate);
  await expect(changedRow.getByTestId('timeline-value')).not.toContainText(oldRate);
  await expect(changedRow.getByTestId('timeline-value')).not.toContainText('rateCalculator');
  await expect(booleanRow.getByTestId('timeline-value')).toContainText('true→false');
  await expect(booleanRow.getByRole('button', { name: /Copy (previous|new)/ })).toHaveCount(0);
  await expect(smallNumberRow.getByTestId('timeline-value')).toContainText('1→2');
  await expect(smallNumberRow.getByRole('button', { name: /Copy (previous|new)/ })).toHaveCount(0);

  for (const row of [changedRow, booleanRow, smallNumberRow]) {
    const valueDiff = row.getByTestId('value-diff');
    const beforeBox = await valueDiff.getByTestId('value-before').boundingBox();
    const afterBox = await valueDiff.getByTestId('value-after').boundingBox();
    expect(beforeBox).not.toBeNull();
    expect(afterBox).not.toBeNull();
    expect(Math.abs(beforeBox!.x - afterBox!.x)).toBeLessThan(1);
    expect(afterBox!.y).toBeGreaterThan(beforeBox!.y);
  }

  const changedBeforeColor = await changedRow.getByTestId('value-before').getByTestId('copyable-value-text').evaluate(
    (element) => getComputedStyle(element).color,
  );
  const changedAfterColor = await changedRow.getByTestId('value-after').getByTestId('copyable-value-text').evaluate(
    (element) => getComputedStyle(element).color,
  );
  expect(changedAfterColor).not.toBe(changedBeforeColor);

  const changedRowBox = await changedRow.boundingBox();
  expect(changedRowBox).not.toBeNull();
  expect(changedRowBox!.height).toBeLessThan(120);

  // The mobile timeline keeps a compact, fully disclosable slot column,
  // hides step, folds contract into variable, and avoids horizontal panning.
  await expect(page.getByRole('columnheader', { name: 'Slot' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Step' })).toBeHidden();
  const slotReference = changedRow.getByTestId('slot-reference');
  await expect(slotReference).toBeVisible();
  await expect(slotReference).toContainText('7');
  await expect(page.getByTestId('step-reference').first()).toBeHidden();
  await expect(changedRow.getByRole('link', { name: 'ResupplyPairDeployer' })).toBeVisible();
  await slotReference.getByText('7', { exact: true }).click();
  const slotDetail = page.getByRole('dialog');
  await expect(slotDetail).toContainText(slots[1].slot);
  await expect(slotDetail.getByRole('button', { name: 'Copy slot' })).toBeVisible();
  await page.keyboard.press('Escape');

  await smallNumberRow.getByText('_status', { exact: true }).click();
  const scalarDetail = page.getByRole('dialog', { name: 'Variable details: _status' });
  await expect(scalarDetail).toContainText('_status');
  await expect(scalarDetail).toContainText('uint8');
  await expect(scalarDetail).toContainText(contract.storage_address);
  await expect(scalarDetail.getByRole('button', { name: 'Copy full path' })).toBeVisible();
  await page.keyboard.press('Escape');

  const scroll = page.getByTestId('data-table-scroll');
  const scrollState = await scroll.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(scrollState.scrollWidth).toBeLessThanOrEqual(scrollState.clientWidth + 1);

  // Value mode also controls the numeric slot representation.
  await page.getByRole('button', { name: 'Hex' }).click();
  const hexSlotReference = slotReference.getByText('0x7', { exact: true });
  await expect(hexSlotReference).toBeVisible();
  await hexSlotReference.click();
  await expect(page.getByRole('dialog')).toContainText(slots[1].slot);
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Decoded' }).click();
  await expect(slotReference.getByText('7', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Grouped' }).click();
  const contractSection = page.getByRole('heading', { name: 'ResupplyPairDeployer' }).locator('xpath=ancestor::section');
  await contractSection.getByTestId('contract-toggle').click();
  const groupedAddressRow = contractSection.getByText('rateCalculator', { exact: true }).locator('xpath=ancestor::tr');
  const groupedNoopRow = contractSection.getByText('oracle', { exact: true }).locator('xpath=ancestor::tr');
  const groupedBooleanRow = contractSection.getByText('processed', { exact: true }).locator('xpath=ancestor::tr');
  const groupedSmallNumberRow = contractSection.getByText('_status', { exact: true }).locator('xpath=ancestor::tr');
  await expect(groupedAddressRow.getByTestId('value-diff').getByRole('button', { name: 'Copy value' })).toHaveCount(2);
  await expect(groupedNoopRow.getByTestId('value-noop-indicator')).toBeVisible();
  await expect(groupedNoopRow.getByTestId('value-arrow')).toHaveCount(0);
  await expect(groupedBooleanRow.getByTestId('value-diff').getByRole('button', { name: 'Copy value' })).toHaveCount(0);
  await expect(groupedBooleanRow.getByRole('link')).toHaveCount(0);
  await expect(groupedSmallNumberRow.getByTestId('value-diff').getByRole('button', { name: 'Copy value' })).toHaveCount(0);
  await expect(groupedBooleanRow.getByTestId('value-diff').locator('[aria-haspopup="dialog"]')).toHaveCount(0);
  await expect(groupedSmallNumberRow.getByTestId('value-diff').locator('[aria-haspopup="dialog"]')).toHaveCount(0);
  const groupedAddressDisclosures = groupedAddressRow.getByTestId('value-diff').locator('[aria-haspopup="dialog"]');
  await expect(groupedAddressDisclosures).toHaveCount(2);
  await groupedAddressDisclosures.first().hover();
  const addressDetail = page.getByRole('dialog');
  await expect(addressDetail).toHaveText(oldRate);
  const addressDetailMetrics = await addressDetail.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    right: element.getBoundingClientRect().right,
  }));
  expect(addressDetailMetrics.scrollWidth).toBeLessThanOrEqual(addressDetailMetrics.clientWidth);
  expect(addressDetailMetrics.right).toBeLessThanOrEqual(383);
  await groupedAddressRow.getByText('rateCalculator', { exact: true }).hover();
  await expect(addressDetail).toHaveCount(0);
  // The slot column (and its copy action) is hidden at mobile widths.
  await expect(groupedSmallNumberRow.getByRole('button', { name: 'Copy value' })).toHaveCount(0);
});

test('timeline contains single-key mapping paths on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  const account = '0xe53800000000000000000000000000000000aaf0';
  const implementation = '0x8888888888888888888888888888888888888888';
  const scalarSlot = configScalarSlot({
    slot: 25,
    variable: 'balance_of',
    typeLabel: 'uint256',
    beforeValue: '579900000000000000000',
    afterValue: '600580000000000000000',
    beforeEncoded: `0x${'00'.repeat(31)}01`,
    afterEncoded: `0x${'00'.repeat(31)}02`,
    step: 1700,
  });
  const slot = {
    ...scalarSlot,
    variable_path: `balance_of[${account}]`,
    is_static_slot: false,
    is_mapping: true,
    params: [{ type: 'address', value: account, label: null }],
  };
  const contract = resolutionContract({
    storage_address: '0x6666666666666666666666666666666666666666',
    code_addresses: ['0x6666666666666666666666666666666666666666'],
    implementation_addresses: [implementation],
    name: 'YearnV3Vault',
    is_verified: true,
    layout_available: true,
    resolution: { resolved: 1, total: 1 },
    slots: [slot],
  });
  const response = resolutionResponse([
    contract,
    resolutionContract({
      storage_address: '0x7777777777777777777777777777777777777777',
      code_addresses: ['0x7777777777777777777777777777777777777777'],
      name: 'OtherContract',
    }),
  ]);
  response.global_order = [{
    ordinal: 0,
    step: slot.changes[0].step,
    storage_address: contract.storage_address,
    slot: slot.slot,
    event_index: 0,
  }];
  await page.route(`**/api/slotscan/tx/1/${RESOLUTION_TX}*`, async (route) => {
    await route.fulfill({ json: response });
  });

  await page.goto(`/1/tx/${RESOLUTION_TX}?view=timeline`);

  const row = page.getByTestId('timeline-event');
  const variableCell = row.getByTestId('timeline-variable');
  const valueCell = row.getByTestId('timeline-value');
  const path = row.getByTestId('keyed-variable-path');
  const primary = row.getByTestId('keyed-variable-primary');
  const base = row.getByTestId('keyed-variable-base');
  const disclosure = variableCell.locator('[aria-haspopup="dialog"]');
  await expect(primary).toContainText('balance_of');
  await expect(primary).toContainText('0xe538...aaf0');
  expect(await path.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect(await valueCell.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  const variableBox = await variableCell.boundingBox();
  const valueBox = await valueCell.boundingBox();
  expect(variableBox).not.toBeNull();
  expect(valueBox).not.toBeNull();
  expect(variableBox!.x + variableBox!.width).toBeLessThanOrEqual(valueBox!.x + 1);

  await expect(disclosure).toHaveAttribute('aria-expanded', 'false');
  await base.click();
  await expect(disclosure).toHaveAttribute('aria-expanded', 'true');
  const pathDetail = page.getByRole('dialog', { name: `Variable details: ${slot.variable_path}` });
  await expect(pathDetail).toContainText(slot.variable_path);
  await expect(pathDetail).toContainText('uint256');
  await expect(pathDetail).toContainText('YearnV3Vault');
  await expect(pathDetail).toContainText(contract.storage_address);
  await expect(pathDetail).toContainText(implementation);
  await expect(pathDetail.getByText('Written via', { exact: true })).toHaveCount(0);
  await expect(pathDetail.getByText('via', { exact: true })).toBeVisible();
  await expect(pathDetail.getByRole('link', { name: contract.storage_address })).toHaveAttribute(
    'href',
    `https://etherscan.io/address/${contract.storage_address}`,
  );
  await expect(pathDetail.getByRole('link', { name: implementation })).toHaveAttribute(
    'href',
    `https://etherscan.io/address/${implementation}`,
  );
  const contractLabelBox = await pathDetail.getByText('Contract', { exact: true }).boundingBox();
  const variableLabelBox = await pathDetail.getByText('Variable', { exact: true }).boundingBox();
  expect(contractLabelBox).not.toBeNull();
  expect(variableLabelBox).not.toBeNull();
  expect(variableLabelBox!.y).toBeLessThan(contractLabelBox!.y);
  const variableNameSize = await pathDetail.getByTestId('detail-variable-name').first().evaluate(
    (element) => parseFloat(getComputedStyle(element).fontSize),
  );
  const variableKeySize = await pathDetail.getByTestId('detail-variable-key').evaluate(
    (element) => parseFloat(getComputedStyle(element).fontSize),
  );
  expect(variableKeySize).toBeLessThan(variableNameSize);
  const appearance = await pathDetail.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      backgroundColor: style.backgroundColor,
      borderRadius: parseFloat(style.borderRadius),
      boxShadow: style.boxShadow,
    };
  });
  expect(appearance.backgroundColor).toBe(await page.evaluate(
    () => getComputedStyle(document.body).backgroundColor,
  ));
  expect(appearance.borderRadius).toBeGreaterThan(0);
  expect(appearance.boxShadow).not.toBe('none');
  const detailBox = await pathDetail.boundingBox();
  expect(detailBox).not.toBeNull();
  expect(detailBox!.x).toBeGreaterThanOrEqual(7);
  expect(detailBox!.x + detailBox!.width).toBeLessThanOrEqual(383);
  expect(detailBox!.height).toBeLessThanOrEqual(180);

  await pathDetail.getByRole('button', { name: 'Copy full path' }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(slot.variable_path);
  await pathDetail.getByRole('button', { name: 'Copy storage contract address' }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(contract.storage_address);
  await pathDetail.getByRole('button', { name: `Copy implementation address 0x8888...8888` }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(implementation);

  await page.keyboard.press('Escape');
  await expect(pathDetail).toHaveCount(0);
  await expect(disclosure).toHaveAttribute('aria-expanded', 'false');

  await page.setViewportSize({ width: 1280, height: 800 });
  await base.hover();
  await expect(page.getByRole('dialog', { name: `Variable details: ${slot.variable_path}` })).toBeVisible();
});

test('transaction summary, controls, and copy actions stay compact at wide widths', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  const contracts = ['11', '22', '33', '44'].map((byte) => resolutionContract({
    storage_address: `0x${byte.repeat(20)}`,
    code_addresses: [`0x${byte.repeat(20)}`],
    name: `Contract${byte}`,
    is_verified: true,
    layout_available: true,
  }));
  await page.route(`**/api/slotscan/tx/1/${RESOLUTION_TX}*`, async (route) => {
    await route.fulfill({ json: resolutionResponse(contracts) });
  });

  await page.goto(`/1/tx/${RESOLUTION_TX}`);

  const reportBox = await page.getByTestId('transaction-report').boundingBox();
  const summaryBox = await page.getByTestId('transaction-summary').boundingBox();
  expect(reportBox).not.toBeNull();
  expect(summaryBox).not.toBeNull();
  expect(reportBox!.width).toBeLessThanOrEqual(1350);
  expect(summaryBox!.width).toBeLessThanOrEqual(970);
  await expect(page.getByText('TXN', { exact: true })).toBeVisible();
  await expect(page.getByText('SUCCESS', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('group', { name: 'View' })).toBeVisible();
  await expect(page.getByRole('group', { name: 'Values' })).toBeVisible();
  await expect(page.getByText('Values', { exact: true })).toHaveCount(0);
  const viewBox = await page.getByRole('group', { name: 'View' }).boundingBox();
  const valuesBox = await page.getByRole('group', { name: 'Values' }).boundingBox();
  expect(viewBox).not.toBeNull();
  expect(valuesBox).not.toBeNull();
  expect(viewBox!.height).toBeLessThanOrEqual(24);
  expect(valuesBox!.height).toBeLessThanOrEqual(24);
  expect(viewBox!.width).toBeGreaterThanOrEqual(134);
  expect(Math.abs(viewBox!.x - valuesBox!.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(viewBox!.width - valuesBox!.width)).toBeLessThanOrEqual(1);
  expect(await page.getByRole('button', { name: 'Timeline' }).evaluate(
    (element) => element.scrollWidth <= element.clientWidth,
  )).toBe(true);
  expect(valuesBox!.y).toBeGreaterThanOrEqual(viewBox!.y + viewBox!.height);
  const searchBox = await page.getByPlaceholder('Search contract, address, slot, or variable').boundingBox();
  const controlsBox = await page.getByTestId('transaction-view-controls').boundingBox();
  expect(searchBox).not.toBeNull();
  expect(controlsBox).not.toBeNull();
  expect(searchBox!.width).toBeLessThanOrEqual(321);
  expect(searchBox!.x - (viewBox!.x + viewBox!.width)).toBeGreaterThanOrEqual(11);
  expect(searchBox!.x - (viewBox!.x + viewBox!.width)).toBeLessThanOrEqual(13);
  expect(Math.abs(
    searchBox!.y + searchBox!.height / 2 - (controlsBox!.y + controlsBox!.height / 2),
  )).toBeLessThanOrEqual(1);
  await expect(page.getByText('Contract', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Activity', { exact: true })).toHaveCount(0);

  await page.getByRole('button', { name: 'Copy sender address' }).click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(RESOLUTION_FROM);
  await expect(page.getByRole('button', { name: 'Copy recipient address' })).toBeVisible();
});

test('transaction summary and controls wrap cleanly at narrow widths', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const contracts = ['11', '22', '33', '44'].map((byte) => resolutionContract({
    storage_address: `0x${byte.repeat(20)}`,
    code_addresses: [`0x${byte.repeat(20)}`],
    name: `Contract${byte}`,
    is_verified: true,
    layout_available: true,
  }));
  await page.route(`**/api/slotscan/tx/1/${RESOLUTION_TX}*`, async (route) => {
    await route.fulfill({ json: { ...resolutionResponse(contracts), status: 'reverted' } });
  });

  await page.goto(`/1/tx/${RESOLUTION_TX}`);

  await expect(page.getByText('TXN', { exact: true })).toBeVisible();
  await expect(page.getByText('Reverted', { exact: true })).toBeVisible();
  await expect(page.getByText('SUCCESS', { exact: true })).toHaveCount(0);
  const viewBox = await page.getByRole('group', { name: 'View' }).boundingBox();
  const valuesBox = await page.getByRole('group', { name: 'Values' }).boundingBox();
  const searchBox = await page.getByPlaceholder('Search contract, address, slot, or variable').boundingBox();
  expect(viewBox).not.toBeNull();
  expect(valuesBox).not.toBeNull();
  expect(searchBox).not.toBeNull();
  expect(Math.abs(viewBox!.x - valuesBox!.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(viewBox!.width - valuesBox!.width)).toBeLessThanOrEqual(1);
  expect(valuesBox!.y).toBeGreaterThanOrEqual(viewBox!.y + viewBox!.height);
  expect(searchBox!.y).toBeGreaterThanOrEqual(Math.max(
    viewBox!.y + viewBox!.height,
    valuesBox!.y + valuesBox!.height,
  ));
  const overflowing = await page.evaluate(() => Array.from(document.querySelectorAll<HTMLElement>('body *'))
    .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
    .map((element) => `${element.tagName.toLowerCase()}.${element.className}`)
    .slice(0, 10));
  expect(overflowing).toEqual([]);
});

test('transient resolution retries once automatically and then offers a manual retry', async ({ page }) => {
  let requests = 0;
  await page.route(`**/api/slotscan/tx/1/${RESOLUTION_TX}*`, async (route) => {
    requests += 1;
    const contract = requests < 3
      ? resolutionContract({
          resolution_status: 'timed_out',
          errors: ['0x1111: TimeoutError: historical resolution failed'],
        })
      : resolutionContract({
          name: 'RecoveredContract',
          is_verified: true,
          layout_available: true,
          resolution_status: 'resolved',
          resolution: { resolved: 1, total: 1 },
        });
    await route.fulfill({ json: resolutionResponse([contract]) });
  });

  await page.goto(`/1/tx/${RESOLUTION_TX}`);

  await expect.poll(() => requests).toBe(2);
  await expect(page.getByRole('heading', { name: 'Resolution timed out' })).toBeVisible();
  const retry = page.getByRole('button', { name: 'Retry resolution' });
  await expect(retry).toBeVisible();
  await retry.click();
  await expect(page.getByRole('heading', { name: 'RecoveredContract' })).toBeVisible();
  await expect(retry).toHaveCount(0);
});

test('all writes remain visible without interpretive classification controls', async ({ page }) => {
  await page.goto(`/1/tx/${RESTORED_TX}`);

  await expect(page.getByRole('heading', { name: '0x7fe79d...2b7cac' })).toBeVisible();
  await expect(page.getByTestId('summary-writes').getByText('5', { exact: true })).toBeVisible();
  await expect(page.getByTestId('summary-slots').getByText('4', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Grouped' })).toHaveAttribute('aria-pressed', 'true');
  await page.getByTestId('contract-toggle').click();
  for (const step of ['719', '777', '920', '1432']) {
    await expect(page.getByText(step, { exact: true })).toBeVisible();
  }

  await page.getByRole('button', { name: 'Expand write history' }).click();
  await expect(page.getByText('1496', { exact: true })).toBeVisible();
  await expect(page.getByText('1/2')).toBeVisible();
  await expect(page.getByText('2/2')).toBeVisible();
  await expect(page.getByText('restored', { exact: true })).toHaveCount(0);
});

test('reverted child writes remain grouped and in the global timeline', async ({ page }) => {
  await page.goto(`/1/tx/${REVERTED_WRITES_TX}`);

  await expect(page.getByRole('heading', { name: '0x561dd6...742ae2' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Grouped' })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByPlaceholder('Search contract, address, slot, or variable')).toBeVisible();
  await expect(page.getByText(/reverted writes?/, { exact: true }).first()).toBeVisible();

  await page.getByRole('button', { name: 'Timeline' }).click();
  await expect(page.getByTestId('timeline-event')).toHaveCount(386);
  await expect(page.getByText('reverted', { exact: true }).first()).toBeVisible();
  const firstTimelineRow = page.getByTestId('timeline-event').first();
  const slotBox = await firstTimelineRow.getByTestId('slot-reference').boundingBox();
  const stepBox = await firstTimelineRow.getByTestId('step-reference').boundingBox();
  expect(slotBox).not.toBeNull();
  expect(stepBox).not.toBeNull();
  expect(slotBox!.x + slotBox!.width).toBeLessThanOrEqual(stepBox!.x);
  await page.getByRole('button', { name: 'Hex' }).click();
  await expect(page).toHaveURL(new RegExp('values=hex'));
  await expect(page.getByRole('button', { name: 'Hex' })).toHaveAttribute('aria-pressed', 'true');
  await expect(firstTimelineRow.getByTestId('timeline-value')).toContainText('0x');
});

test('verified sources recover proxy, namespace, legacy, and Vyper variable names', async ({ page }) => {
  await page.goto(`/1/tx/${SOURCE_LAYOUT_TX}`);

  await expect(page.getByTestId('summary-writes').getByText('74', { exact: true })).toBeVisible();
  await expect(page.getByTestId('summary-slots').getByText('51', { exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Storage owners' })).toHaveCount(0);
  await expect(page.getByTestId('contract-toggle')).toHaveCount(13);
  for (const toggle of await page.getByTestId('contract-toggle').all()) {
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  }
  await expect(page.getByRole('heading', { name: 'GnosisSafe' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'YearnV3Vault' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Vat' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'WithdrawalQueueERC721' })).toBeVisible();

  const safeSection = page.getByRole('heading', { name: 'GnosisSafe' }).locator('xpath=ancestor::section');
  await expect(safeSection.getByText('0x1638...0ff7', { exact: true })).toBeVisible();
  await expect(safeSection.getByRole('button', { name: 'Copy' })).toBeVisible();

  const search = page.getByPlaceholder('Search contract, address, slot, or variable');
  await search.fill('nonreentrant.lock');
  await expect(page.getByTestId('contract-toggle')).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByText('nonreentrant.lock', { exact: true })).toBeVisible();
  // The lock is written back to its starting value, so it renders once
  // with the unchanged indicator instead of a before → after arrow.
  await expect(page.getByTestId('value-noop-indicator').first()).toBeVisible();

  await search.fill('current_debt');
  await expect(page.getByText('current_debt', { exact: true })).toHaveCount(2);

  await search.fill('lastRequestId');
  await expect(page.getByText('lastRequestId', { exact: true })).toBeVisible();

  const valueDiff = page.getByTestId('value-diff').first();
  const beforeBox = await valueDiff.getByTestId('value-before').boundingBox();
  const afterBox = await valueDiff.getByTestId('value-after').boundingBox();
  const arrowBox = await valueDiff.getByTestId('value-arrow').boundingBox();
  expect(beforeBox).not.toBeNull();
  expect(afterBox).not.toBeNull();
  expect(arrowBox).not.toBeNull();
  expect(Math.abs(beforeBox!.x - afterBox!.x)).toBeLessThan(1);
  expect(Math.abs(beforeBox!.y - arrowBox!.y)).toBeLessThan(1);
  expect(arrowBox!.x).toBeGreaterThanOrEqual(beforeBox!.x + beforeBox!.width);
  expect(afterBox!.y).toBeGreaterThan(beforeBox!.y);
});

test('nested mappings inside mapping structs show the full resolved path', async ({ page }) => {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto(`/1/tx/${NESTED_STRUCT_MAPPING_TX}`);

  const search = page.getByPlaceholder('Search contract, address, slot, or variable');
  await search.fill('lastExecutionTimestamp');

  await expect(page.getByRole('heading', { name: 'borgCore' })).toBeVisible();
  const variable = page.getByTestId('keyed-variable-path');
  await expect(variable.getByText('lastExecutionTimestamp', { exact: true })).toBeVisible();
  await expect(variable.getByText('policy', { exact: true })).toBeVisible();
  await expect(variable.getByText('0x40a2...130d', { exact: true })).toBeVisible();
  await expect(variable.getByText('methods', { exact: true })).toBeVisible();
  await expect(variable.getByText('0x8d80ff0a', { exact: true })).toBeVisible();
  await expect(variable.getByText('uint256', { exact: true })).toBeVisible();
  await expect(variable.getByText('PolicyItem', { exact: true })).toHaveCount(0);

  const primaryBox = await variable.getByTestId('keyed-variable-primary').boundingBox();
  const contextBox = await variable.getByTestId('keyed-variable-context').boundingBox();
  const nestedKeyLines = variable.getByTestId('keyed-variable-key-line');
  await expect(nestedKeyLines).toHaveCount(2);
  const policyLineBox = await nestedKeyLines.nth(0).boundingBox();
  const methodsLineBox = await nestedKeyLines.nth(1).boundingBox();
  expect(primaryBox).not.toBeNull();
  expect(contextBox).not.toBeNull();
  expect(policyLineBox).not.toBeNull();
  expect(methodsLineBox).not.toBeNull();
  expect(contextBox!.y).toBeGreaterThan(primaryBox!.y);
  expect(methodsLineBox!.y).toBeGreaterThan(policyLineBox!.y);

  const copy = variable.getByRole('button', { name: 'Copy full path' });
  await expect(copy).toBeVisible();
  await copy.click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(
    'policy[0x40a2accbd92bca938b02010e17a5b8929b49130d].methods[0x8d80ff0a].lastExecutionTimestamp',
  );

  await page.getByRole('button', { name: 'Timeline' }).click();
  await expect(page).toHaveURL(new RegExp(`/${NESTED_STRUCT_MAPPING_TX}\\?.*view=timeline`));
  const timelineVariable = page.getByTestId('keyed-variable-path');
  await expect(timelineVariable.getByTestId('keyed-variable-primary')).toHaveText('lastExecutionTimestamp');
  await expect(timelineVariable.getByTestId('keyed-variable-key-line')).toHaveCount(2);
});

test('multi-key mappings stay compact and copy their complete path', async ({ page }) => {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto(`/1/tx/${SOURCE_LAYOUT_TX}?focus=${LIDO_ADDRESS}`);

  await expect(page.getByRole('heading', { name: '0x3353c2...14cd60' })).toBeVisible();
  const lidoSection = page.getByRole('heading', { name: 'Lido' }).locator('xpath=ancestor::section');
  await expect(lidoSection.getByTestId('contract-toggle')).toHaveAttribute('aria-expanded', 'true');
  const keyedVariables = lidoSection.getByTestId('keyed-variable-path');
  await expect(keyedVariables).toHaveCount(3);

  const allowance = keyedVariables.filter({ hasText: 'allowances' }).first();
  await expect(allowance.getByTestId('keyed-variable-primary')).toHaveText('allowances');
  await expect(allowance.getByText('0x470e...7435', { exact: true })).toBeVisible();
  await expect(allowance.getByText('0x889e...f9b1', { exact: true })).toBeVisible();
  await expect(allowance.getByText('uint256', { exact: true })).toBeVisible();
  await expect(allowance).not.toContainText('0x470e0e048f85cfd72eef325895e02c8d297e7435');

  const keyLines = allowance.getByTestId('keyed-variable-key-line');
  await expect(keyLines).toHaveCount(2);
  const firstKeyBox = await keyLines.nth(0).boundingBox();
  const secondKeyBox = await keyLines.nth(1).boundingBox();
  expect(firstKeyBox).not.toBeNull();
  expect(secondKeyBox).not.toBeNull();
  expect(secondKeyBox!.y).toBeGreaterThan(firstKeyBox!.y);
  expect(Math.abs(secondKeyBox!.x - firstKeyBox!.x)).toBeLessThan(1);

  const shares = keyedVariables.filter({ hasText: 'shares' }).first();
  await expect(shares.getByTestId('keyed-variable-key-line')).toHaveCount(0);
  await expect(shares.getByTestId('keyed-variable-primary')).toContainText('shares[0x470e...7435]');

  const copy = allowance.getByRole('button', { name: 'Copy full path' });
  await copy.click();
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(
    'allowances[0x470e0e048f85cfd72eef325895e02c8d297e7435][0x889edc2edab5f40e902b864ad4d7ade8e412f9b1]',
  );
});

test('legacy contract transaction URLs redirect to the complete focused report', async ({ page }) => {
  await page.goto(`/1/${GNOSIS_SAFE_ADDRESS}?tx=${SOURCE_LAYOUT_TX}`);
  await expect(page).toHaveURL(`/1/tx/${SOURCE_LAYOUT_TX}?focus=${GNOSIS_SAFE_ADDRESS}`);
  await expect(page.getByTestId('contract-toggle')).toHaveCount(13);
  const safeSection = page.getByRole('heading', { name: 'GnosisSafe' }).locator('xpath=ancestor::section');
  await expect(safeSection.getByTestId('contract-toggle')).toHaveAttribute('aria-expanded', 'true');

  await page.goto(`/1/${GNOSIS_SAFE_ADDRESS}/tx/${SOURCE_LAYOUT_TX}`);
  await expect(page).toHaveURL(`/1/tx/${SOURCE_LAYOUT_TX}?focus=${GNOSIS_SAFE_ADDRESS}`);
});

test('storage evidence remains contained and operable at narrow widths', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/1/tx/${SOURCE_LAYOUT_TX}?focus=${LIDO_ADDRESS}`);

  const lidoSection = page.getByRole('heading', { name: 'Lido' }).locator('xpath=ancestor::section');
  const toggle = lidoSection.getByTestId('contract-toggle');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await toggle.focus();
  await page.keyboard.press('Enter');
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await page.keyboard.press('Enter');
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');

  const scroller = lidoSection.getByTestId('data-table-scroll');
  await expect(scroller).toBeVisible();
  // With slot/step hidden at mobile widths the table fits the viewport.
  expect(await scroller.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  const overflowing = await page.evaluate(() => Array.from(document.querySelectorAll<HTMLElement>('body *'))
    .filter((element) => (
      !element.closest('[data-testid="data-table-scroll"]')
      && element.getBoundingClientRect().right > window.innerWidth + 1
    ))
    .map((element) => `${element.tagName.toLowerCase()}.${element.className}`)
    .slice(0, 10));
  expect(overflowing).toEqual([]);
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflowX)).toBe('hidden');
});

test('storage detail disclosure matches the active theme and supports focus and Escape', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' });
  await page.goto(`/1/tx/${NESTED_STRUCT_MAPPING_TX}`);
  await page.getByPlaceholder('Search contract, address, slot, or variable').fill('lastExecutionTimestamp');

  const variable = page.getByTestId('keyed-variable-path');
  await expect(variable.getByText('0x40a2...130d', { exact: true })).not.toHaveAttribute('title', /.+/);
  const disclosure = variable.locator('xpath=ancestor::*[@tabindex="0"][1]');
  await disclosure.focus();
  const lightDetail = page.getByRole('dialog');
  await expect(lightDetail).toBeVisible();
  await expect(lightDetail).toHaveCount(1);
  const lightStyle = await lightDetail.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      backgroundColor: style.backgroundColor,
      borderRadius: style.borderRadius,
      boxShadow: style.boxShadow,
      color: style.color,
      paddingTop: style.paddingTop,
    };
  });
  expect(lightStyle).toMatchObject({
    backgroundColor: 'rgb(255, 255, 255)',
    borderRadius: '8px',
    color: 'rgb(51, 51, 51)',
    paddingTop: '8px',
  });
  expect(lightStyle.boxShadow).not.toBe('none');

  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);

  await page.getByRole('button', { name: 'Switch to dark mode' }).click();
  await disclosure.focus();
  const darkDetail = page.getByRole('dialog');
  await expect(darkDetail).toBeVisible();
  await expect(darkDetail).toHaveCSS('background-color', 'rgb(17, 17, 17)');
  await expect(darkDetail).toHaveCSS('color', 'rgb(211, 211, 211)');
});
