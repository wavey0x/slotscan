import { expect, test, type Page } from '@playwright/test';

const VOTING_ESCROW_ADDRESS = '0x5f3b5dfeb7b28cdbd7faba78963ee202a494e2a2';
const NAMED_ADDRESS = '0x1234567890abcdef1234567890abcdef12345678';
const UNNAMED_ADDRESS = '0xabcdefabcdefabcdefabcdefabcdefabcdefabcd';

async function mockContractPage(
  page: Page,
  address: string,
  name: string | null,
  data: {
    variables?: Record<string, unknown>[];
    types?: Record<string, Record<string, unknown>>;
    slots?: Record<string, unknown>[];
  } = {},
) {
  await page.route(`**/api/slotscan/contracts/1/${address}/layout`, async (route) => {
    await route.fulfill({
      json: {
        contract_name: name || '',
        variables: data.variables ?? [],
        types: data.types ?? {},
      },
    });
  });
  await page.route(`**/api/slotscan/contracts/1/${address}`, async (route) => {
    await route.fulfill({
      json: {
        chain_id: 1,
        address,
        name,
        code_hash: null,
        is_proxy: false,
        proxy_type: null,
        implementation_address: null,
        is_verified: true,
        verification_source: 'mock',
        compiler_version: '0.8.30',
        has_layout: true,
      },
    });
  });
  await page.route(`**/api/slotscan/storage/1/${address}*`, async (route) => {
    await route.fulfill({
      json: {
        chain_id: 1,
        address,
        block_number: 1,
        slots: data.slots ?? [],
        is_complete: true,
        is_verified: true,
      },
    });
  });
}

test('address headers label named contracts and keep the compact value switch unlabeled', async ({ page }) => {
  await mockContractPage(page, NAMED_ADDRESS, 'MockVault');
  await page.goto(`/1/${NAMED_ADDRESS}`);

  const header = page.locator('main header');
  await expect(header.getByText('ADDR', { exact: true })).toBeVisible();
  await expect(header.getByRole('heading', { name: 'MockVault' })).toBeVisible();
  await expect(header.getByRole('link', { name: '0x1234...5678' })).toHaveCount(1);
  await expect(header.getByRole('button', { name: 'Copy contract address' })).toHaveCount(1);
  await expect(page.getByRole('group', { name: 'Values' })).toBeVisible();
  await expect(page.getByText('Values', { exact: true })).toHaveCount(0);
});

test('unnamed address headers show the address only once', async ({ page }) => {
  await mockContractPage(page, UNNAMED_ADDRESS, null);
  await page.goto(`/1/${UNNAMED_ADDRESS}`);

  const header = page.locator('main header');
  await expect(header.getByText('ADDR', { exact: true })).toBeVisible();
  await expect(header.getByRole('link', { name: '0xabcd...abcd' })).toHaveCount(1);
  await expect(header.getByRole('button', { name: 'Copy contract address' })).toHaveCount(1);
});

test('mobile layouts keep hidden slot indexes available from the variable disclosure', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockContractPage(page, NAMED_ADDRESS, 'MockVault', {
    variables: [{
      name: 'owner',
      slot: 42,
      offset: 0,
      size: 32,
      type_id: 't_address',
      type_label: 'address',
      provenance: 'compiler_layout',
      confidence: 'exact',
    }],
    types: {
      t_address: {
        id: 't_address',
        label: 'address',
        kind: 'value',
        encoding: 'inplace',
        num_bytes: 20,
        element_type: null,
        array_length: null,
        key_type: null,
        value_type: null,
      },
    },
  });
  await page.goto(`/1/${NAMED_ADDRESS}`);

  await expect(page.getByTestId('layout-slot')).toBeHidden();
  await page.getByText('owner', { exact: true }).click();
  const disclosure = page.getByRole('dialog');
  await expect(disclosure).toBeVisible();
  await expect(disclosure.getByText('42', { exact: true })).toBeVisible();
});

test('long slot indexes stay contained within the slot column', async ({ page }) => {
  await mockContractPage(page, VOTING_ESCROW_ADDRESS, 'VotingEscrow', {
    variables: [{
      name: 'nonreentrant.lock',
      slot: 16777215,
      offset: 0,
      size: 32,
      type_id: 't_uint256',
      type_label: 'uint256',
      provenance: 'compiler_layout',
      confidence: 'exact',
    }],
    types: {
      t_uint256: {
        id: 't_uint256',
        label: 'uint256',
        kind: 'value',
        encoding: 'inplace',
        num_bytes: 32,
        element_type: null,
        array_length: null,
        key_type: null,
        value_type: null,
      },
    },
  });
  await page.goto(`/1/${VOTING_ESCROW_ADDRESS}`);

  await expect(page.getByRole('heading', { name: 'Storage layout' })).toBeVisible();
  const row = page.getByText('nonreentrant.lock', { exact: true }).locator('xpath=ancestor::tr');
  const slotCell = row.getByTestId('layout-slot');
  const valueCell = row.locator('td').nth(4);

  await expect(slotCell).toHaveText('16777215');
  expect(await slotCell.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);

  const slotBox = await slotCell.boundingBox();
  const valueBox = await valueCell.boundingBox();
  expect(slotBox).not.toBeNull();
  expect(valueBox).not.toBeNull();
  expect(slotBox!.x + slotBox!.width).toBeLessThanOrEqual(valueBox!.x);
});
