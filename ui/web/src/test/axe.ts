import {expect} from 'vitest';
import {axe} from 'vitest-axe';

/**
 * Fails the test with the list of axe violations, if any. Comparing the
 * violations array (instead of a custom matcher) prints the rule ids and
 * nodes on failure and needs no matcher type augmentation.
 */
export async function expectNoA11yViolations(
  container: Element,
): Promise<void> {
  const results = await axe(container, {
    // jsdom has no layout or canvas, so contrast can't be computed here; it
    // is checked by hand in the browser (web-verify skill).
    rules: {'color-contrast': {enabled: false}},
  });
  expect(results.violations).toEqual([]);
}
