import {describe, expect, it} from 'vitest';

import {cn} from './utils';

describe('cn', () => {
  it('lets the later Tailwind class win a conflict', () => {
    expect(cn('px-2 text-sm', 'px-4')).toBe('text-sm px-4');
  });

  it('drops falsy values', () => {
    expect(cn('font-medium', false, undefined, 'underline')).toBe(
      'font-medium underline',
    );
  });
});
