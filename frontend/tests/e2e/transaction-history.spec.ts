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
    from_address: null,
    to_address: null,
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
  await expect(firstTimelineRow.getByTestId('value-before')).toContainText('0x');
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

  await expect(page.getByText('Contract', { exact: true })).toBeVisible();
  await expect(page.getByText('Activity', { exact: true })).toBeVisible();
  const safeSection = page.getByRole('heading', { name: 'GnosisSafe' }).locator('xpath=ancestor::section');
  await expect(safeSection.getByText('0x1638...0ff7', { exact: true })).toBeVisible();
  await expect(safeSection.getByRole('button', { name: 'Copy' })).toBeVisible();

  const search = page.getByPlaceholder('Search contract, address, slot, or variable');
  await search.fill('nonreentrant.lock');
  await expect(page.getByTestId('contract-toggle')).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByText('nonreentrant.lock', { exact: true })).toBeVisible();

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

  await search.fill('current_debt');
  await expect(page.getByText('current_debt', { exact: true })).toHaveCount(2);

  await search.fill('lastRequestId');
  await expect(page.getByText('lastRequestId', { exact: true })).toBeVisible();
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
  expect(await scroller.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
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

test('storage detail disclosure supports focus and Escape', async ({ page }) => {
  await page.goto(`/1/tx/${NESTED_STRUCT_MAPPING_TX}`);
  await page.getByPlaceholder('Search contract, address, slot, or variable').fill('lastExecutionTimestamp');

  const variable = page.getByTestId('keyed-variable-path');
  const disclosure = variable.locator('xpath=ancestor::*[@tabindex="0"][1]');
  await disclosure.focus();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
});
