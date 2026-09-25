import {describe, expect, it} from 'vitest';

import {safeHttpUrl} from './url';

describe('safeHttpUrl', () => {
  it('keeps absolute http and https URLs', () => {
    expect(safeHttpUrl('https://wire.vendornews.example/2026/09/24/x')).toEqual(
      {
        href: 'https://wire.vendornews.example/2026/09/24/x',
        hostname: 'wire.vendornews.example',
      },
    );
    expect(safeHttpUrl('http://press.marketline.example/a?b=1')?.href).toBe(
      'http://press.marketline.example/a?b=1',
    );
  });

  it('reports the host the link really opens', () => {
    // Userinfo can't disguise the destination.
    expect(safeHttpUrl('https://acme.example@evil.example/x')?.hostname).toBe(
      'evil.example',
    );
  });

  it('rejects every other scheme and anything unparsable', () => {
    for (const url of [
      'javascript:alert(document.cookie)',
      ' JavaScript:alert(1)',
      'data:text/html,<script>alert(1)</script>',
      'vbscript:msgbox(1)',
      'ftp://files.example/x',
      '/relative/path',
      '//no-scheme.example/x',
      'not a url',
      '',
    ]) {
      expect(safeHttpUrl(url)).toBeUndefined();
    }
  });
});
