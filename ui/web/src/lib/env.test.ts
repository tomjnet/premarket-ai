import {describe, expect, it} from 'vitest';

import {apiUrl, readEnv} from './env';

describe('readEnv', () => {
  it('defaults to live mode, /api and a 900 s token', () => {
    expect(readEnv({})).toEqual({
      apiMode: 'live',
      apiBaseUrl: '/api',
      mockTokenTtlS: 900,
    });
  });

  it('reads the variables and drops a trailing slash', () => {
    expect(
      readEnv({
        VITE_API_MODE: 'mock',
        VITE_API_BASE_URL: 'https://api.example/v1/',
        VITE_MOCK_TOKEN_TTL_S: '60',
      }),
    ).toEqual({
      apiMode: 'mock',
      apiBaseUrl: 'https://api.example/v1',
      mockTokenTtlS: 60,
    });
  });

  it('fails loudly on a wrong mode instead of guessing', () => {
    expect(() => readEnv({VITE_API_MODE: 'Mock'})).toThrow(
      'Invalid VITE_* settings: VITE_API_MODE',
    );
  });

  it('rejects a token lifetime that is not a positive integer', () => {
    expect(() => readEnv({VITE_MOCK_TOKEN_TTL_S: '0'})).toThrow(
      'VITE_MOCK_TOKEN_TTL_S',
    );
  });
});

describe('apiUrl', () => {
  it('joins the base URL and the contract path', () => {
    expect(apiUrl('/news', '/api')).toBe('/api/news');
    expect(apiUrl('/health', 'https://api.example')).toBe(
      'https://api.example/health',
    );
  });
});
