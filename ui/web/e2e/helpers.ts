import AxeBuilder from '@axe-core/playwright';
import {expect} from '@playwright/test';
import type {Page} from '@playwright/test';

/** Friday 2026-09-25, 09:00 in New York: a trading day with a full feed. */
export const NOW = new Date('2026-09-25T13:00:00Z');

/**
 * Starts the page's clock at NOW, so "today" and the seeded feed are the
 * same on every run, whatever the real date. Time then flows normally, and
 * a test can jump ahead with `page.clock.runFor()`.
 */
export async function pinClock(page: Page): Promise<void> {
  await page.clock.install({time: NOW});
}

/** Opens the login page (optionally in a scenario) and logs in by keyboard. */
export async function logIn(
  page: Page,
  scenario = 'default',
  username = 'trader1',
): Promise<void> {
  await page.goto(`/login?scenario=${scenario}`);
  await page.getByLabel('Username').fill(username);
  await page.getByLabel('Password').fill('demo');
  await page.getByLabel('Password').press('Enter');
  await expect(
    page.getByRole('heading', {level: 1, name: 'News feed'}),
  ).toBeVisible();
}

/**
 * No axe violations for WCAG 2.0–2.2 A and AA, color contrast included
 * (jsdom can't check contrast; a real browser can).
 */
export async function expectNoA11yViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({page})
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze();
  expect(
    results.violations.map(violation => ({
      id: violation.id,
      help: violation.help,
      targets: violation.nodes.map(node => node.target.join(' ')),
    })),
  ).toEqual([]);
}

/** The page is no wider than the viewport (no horizontal scrolling). */
export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}
