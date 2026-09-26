import {expect, test} from '@playwright/test';

import {
  expectNoA11yViolations,
  expectNoHorizontalOverflow,
  logIn,
  pinClock,
} from './helpers';

test.beforeEach(async ({page}) => {
  await pinClock(page);
});

test('the mock backend starts in a real browser', async ({page}) => {
  const messages: string[] = [];
  page.on('console', message => messages.push(message.text()));

  await page.goto('/login');

  await expect(
    page.getByRole('heading', {name: 'Log in to premarket-ai'}),
  ).toBeVisible();
  await expect(page.getByText('Backend: ok')).toBeVisible();
  expect(messages.some(text => text.includes('[MSW] Mocking enabled'))).toBe(
    true,
  );
});

test.describe('accessibility (axe, WCAG 2.2 AA with contrast)', () => {
  for (const colorScheme of ['light', 'dark'] as const) {
    test(`login, feed, detail and 404 in ${colorScheme} mode`, async ({
      page,
    }) => {
      // Four page loads and axe runs: can pass 30 s on a busy machine.
      test.slow();
      await page.emulateMedia({colorScheme});
      await page.goto('/login');
      await expect(page.getByLabel('Username')).toBeVisible();
      await expectNoA11yViolations(page);

      await logIn(page);
      await page.goto('/news?ticker=AAPL&dups=1');
      await expect(page.getByRole('list', {name: 'News items'})).toBeVisible();
      await expectNoA11yViolations(page);

      await page
        .getByRole('list', {name: 'News items'})
        .getByRole('link')
        .first()
        .click();
      await expect(page.getByRole('article')).toBeVisible();
      await expectNoA11yViolations(page);

      await page.goto('/news/999');
      await expect(
        page.getByRole('heading', {name: "This item doesn't exist"}),
      ).toBeVisible();
      await expectNoA11yViolations(page);
    });
  }
});

test.describe('rule badges (contrast in both colour schemes)', () => {
  for (const colorScheme of ['light', 'dark'] as const) {
    test(`flagged feed and a flagged item in ${colorScheme} mode`, async ({
      page,
    }) => {
      // Several page loads and axe runs: more than the default 30 s on a
      // busy machine.
      test.slow();
      await page.emulateMedia({colorScheme});
      await logIn(page);
      await expect(
        page.getByText(
          /^Rule checks: 100 items · 14 duplicates · \d+ flagged$/,
        ),
      ).toBeVisible();

      // Flagged only, duplicates shown: red, amber and neutral badges.
      await page.goto('/news?dups=1&flagged=1');
      const list = page.getByRole('list', {name: 'News items'});
      await expect(list).toBeVisible();
      await expect(list.getByText('FAKE TICKER').first()).toBeVisible();
      await expect(list.getByText('STALE').first()).toBeVisible();
      await expectNoA11yViolations(page);

      await page.goto('/news?q=Quantavex%20to%20be%20acquired%20by%20Praxwood');
      await page
        .getByRole('list', {name: 'News items'})
        .getByRole('link')
        .first()
        .click();
      const rules = page.getByRole('region', {name: 'Rule checks'});
      await expect(
        rules.getByText(
          'reuters-news.test imitates reuters (official domain: reuters.com).',
        ),
      ).toBeVisible();
      await expectNoA11yViolations(page);
    });
  }
});

test.describe('accessibility of error states (red text contrast)', () => {
  for (const colorScheme of ['light', 'dark'] as const) {
    test(`wrong password, failed run and server error in ${colorScheme} mode`, async ({
      page,
    }) => {
      // Four page loads and axe runs: can pass 30 s on a busy machine.
      test.slow();
      await page.emulateMedia({colorScheme});
      await page.goto('/login');
      await page.getByLabel('Username').fill('trader1');
      await page.getByLabel('Password').fill('wrong');
      await page.getByLabel('Password').press('Enter');
      await expect(page.getByText('Wrong username or password.')).toBeVisible();
      await expectNoA11yViolations(page);

      await logIn(page, 'failed');
      await expect(
        page.getByText('The ingest run for this date failed'),
      ).toBeVisible();
      await expectNoA11yViolations(page);

      // Start over in a clean tab (no mock session), in server-error.
      await page.evaluate(() => window.sessionStorage.clear());
      await logIn(page, 'server-error');
      await expect(
        page.getByText('The server had a problem. Try again.'),
      ).toBeVisible();
      await expectNoA11yViolations(page);
    });
  }
});

test.describe('every mock scenario', () => {
  test('default: the day with its summary', async ({page}) => {
    await logIn(page);
    await expect(
      page.getByText('86 items · 14 duplicates hidden · updated 05:30 ET'),
    ).toBeVisible();
  });

  test('empty: no ingest run yet', async ({page}) => {
    await logIn(page, 'empty');
    await expect(
      page.getByText('No ingest run exists for this date yet.'),
    ).toBeVisible();
  });

  test('running: still arriving, and more arrive every 30 s', async ({
    page,
  }) => {
    await logIn(page, 'running');
    await expect(
      page.getByText("Today's feed is still arriving"),
    ).toBeVisible();
    await expect(page.getByText(/^25 items received so far/)).toBeVisible();

    // The feed polls every 30 s; the mock releases 25 more per 30 s.
    await page.clock.runFor(30_000);
    await expect(page.getByText(/^50 items received so far/)).toBeVisible();
    // The rules check each step one poll later.
    await expect(
      page.getByText('Rule checks are running: 25 items checked so far.'),
    ).toBeVisible();
  });

  test('failed: error panel and the items that arrived', async ({page}) => {
    await logIn(page, 'failed');
    await expect(
      page.getByText('The ingest run for this date failed'),
    ).toBeVisible();
    await expect(page.getByRole('list', {name: 'News items'})).toBeVisible();
  });

  test('rules-failed: a notice, and unchecked items say so', async ({page}) => {
    await logIn(page, 'rules-failed');
    await expect(
      page.getByText('Rule checks failed', {exact: true}),
    ).toBeVisible();
    await expect(page.getByText('Not checked yet').first()).toBeVisible();
  });

  test('a date before the rule checks: says they have not run', async ({
    page,
  }) => {
    await logIn(page);
    await page.goto('/news?date=2026-09-18');
    await expect(
      page.getByText("Rule checks haven't run for this date yet."),
    ).toBeVisible();
    await expect(page.getByRole('list', {name: 'Rule checks'})).toHaveCount(0);
  });

  test('slow: skeleton for 2–3 s, then the list', async ({page}) => {
    await logIn(page, 'slow');
    await page.goto('/news?date=2026-09-24');
    const list = page.getByRole('list', {name: 'News items'});
    await expect(page.getByText('Loading the feed…')).toBeAttached();
    await page.waitForTimeout(1000);
    await expect(list).not.toBeVisible();
    await expect(list).toBeVisible({timeout: 10_000});
  });

  test('server-error: plain message and Retry', async ({page}) => {
    await logIn(page, 'server-error');
    await expect(
      page.getByText('The server had a problem. Try again.'),
    ).toBeVisible();
    await expect(page.getByRole('button', {name: 'Retry'})).toBeVisible();
  });

  test('expired-session: 401, one silent refresh, then the feed', async ({
    page,
  }) => {
    // Responses served by the mock's service worker, in order.
    const calls: string[] = [];
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.pathname.startsWith('/api/')) {
        calls.push(`${response.status()} ${url.pathname}`);
      }
    });

    await logIn(page, 'expired-session');
    await expect(page.getByRole('list', {name: 'News items'})).toBeVisible();

    const afterLogin = calls.slice(calls.indexOf('200 /api/auth/login') + 1);
    const news = afterLogin.filter(call => call.endsWith(' /api/news'));
    expect(news).toEqual(['401 /api/news', '200 /api/news']);
    expect(
      afterLogin.filter(call => call.endsWith(' /api/auth/refresh')),
    ).toEqual(['200 /api/auth/refresh']);
  });

  test('logged-out: a reload ends on login with a notice', async ({page}) => {
    await logIn(page, 'logged-out');
    await page.reload();
    await expect(
      page.getByText('Your session expired. Please log in again.'),
    ).toBeVisible();
  });

  test('contract-drift: "Unexpected response from the server"', async ({
    page,
  }) => {
    await logIn(page, 'contract-drift');
    await expect(
      page.getByText('Unexpected response from the server.'),
    ).toBeVisible();
  });

  test('the footer switcher changes the scenario (reload)', async ({page}) => {
    await logIn(page);
    await page.getByLabel('Mock scenario').selectOption('empty');
    await page.getByRole('button', {name: 'Apply (reloads)'}).click();
    await expect(
      page.getByText('No ingest run exists for this date yet.'),
    ).toBeVisible();
    await expect(page.getByLabel('Mock scenario')).toHaveValue('empty');
  });
});

test('keyboard only: log in, move through the feed, open and leave an item', async ({
  page,
}) => {
  await page.goto('/login');
  // The app renders once the mock backend has started.
  await expect(page.getByLabel('Username')).toBeVisible();

  // Tab order: skip link first, then the form.
  await page.keyboard.press('Tab');
  const skipLink = page.getByRole('link', {name: 'Skip to main content'});
  await expect(skipLink).toBeFocused();
  await expect(skipLink).toBeInViewport();
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('Username')).toBeFocused();

  await page.keyboard.type('trader1');
  await page.keyboard.press('Tab');
  await page.keyboard.type('demo');
  await page.keyboard.press('Enter');
  await expect(page.getByRole('list', {name: 'News items'})).toBeVisible();
  await expect(page).toHaveTitle(/^News feed, .* · premarket-ai$/);

  // Filter by keyboard: `/` to search, type, then leave the field.
  await page.keyboard.press('/');
  await expect(page.getByLabel('Search headlines and text')).toBeFocused();
  await page.keyboard.type('Zentrality');
  await expect(page).toHaveURL(/q=Zentrality/);
  await expect(page.getByText(/matching item/)).toBeVisible();
  await page.keyboard.press('Tab');
  await expect(
    page.getByRole('button', {name: 'Apply', exact: true}),
  ).toBeFocused();

  await page.keyboard.press('j');
  const firstLink = page
    .getByRole('list', {name: 'News items'})
    .getByRole('link')
    .first();
  await expect(firstLink).toBeFocused();
  await page.keyboard.press('Enter');

  await expect(page.getByRole('article')).toBeVisible();
  await page.keyboard.press('Tab');
  await expect(
    page.getByRole('link', {name: 'Back to the feed'}),
  ).toBeFocused();
  await page.keyboard.press('Enter');

  await expect(page.getByLabel('Search headlines and text')).toHaveValue(
    'Zentrality',
  );
});

test('360 px wide: nothing overflows on login, feed and detail', async ({
  page,
}) => {
  await page.setViewportSize({width: 360, height: 800});
  await page.goto('/login');
  await expect(page.getByLabel('Username')).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await logIn(page);
  await expectNoHorizontalOverflow(page);

  // The 200+ character headline and the Unicode item.
  await page.goto('/news?q=industry%20conference');
  await page
    .getByRole('list', {name: 'News items'})
    .getByRole('link')
    .first()
    .click();
  await expect(page.getByRole('article')).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test('vendor HTML stays text in a real browser', async ({page}) => {
  let dialogs = 0;
  page.on('dialog', async dialog => {
    dialogs += 1;
    await dialog.dismiss();
  });
  await logIn(page);
  await page.goto('/news?q=Umbrix%20Robotics%20reports');
  await page
    .getByRole('list', {name: 'News items'})
    .getByRole('link')
    .first()
    .click();

  await expect(page.getByRole('article')).toBeVisible();
  await expect(
    page.getByRole('heading', {level: 1, name: /<script>/}),
  ).toBeVisible();
  expect(await page.locator('article img, article script').count()).toBe(0);
  // An onerror or script would fire asynchronously: give it a moment.
  await page.waitForTimeout(1000);
  expect(dialogs).toBe(0);
});
