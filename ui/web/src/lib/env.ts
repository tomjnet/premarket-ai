import {z} from 'zod';

const envSchema = z.object({
  VITE_API_MODE: z.enum(['mock', 'live']).default('live'),
  VITE_API_BASE_URL: z
    .string()
    .default('/api')
    .transform(url => url.replace(/\/+$/, '')),
  VITE_MOCK_TOKEN_TTL_S: z.coerce.number().int().positive().default(900),
});

/** The app settings, read once from the `VITE_*` variables. */
export interface AppEnv {
  apiMode: 'mock' | 'live';
  /** Backend base URL without a trailing slash, for example `/api`. */
  apiBaseUrl: string;
  /** Mock mode only: access-token lifetime in seconds. */
  mockTokenTtlS: number;
}

/**
 * Parses the raw `VITE_*` variables. A wrong value (for example
 * `VITE_API_MODE=Mock`) throws at startup instead of silently running in the
 * wrong mode.
 */
export function readEnv(raw: Record<string, unknown>): AppEnv {
  const result = envSchema.safeParse(raw);
  if (!result.success) {
    const problems = result.error.issues
      .map(issue => `${issue.path.join('.')}: ${issue.message}`)
      .join('; ');
    throw new Error(`Invalid VITE_* settings: ${problems}`);
  }
  return {
    apiMode: result.data.VITE_API_MODE,
    apiBaseUrl: result.data.VITE_API_BASE_URL,
    mockTokenTtlS: result.data.VITE_MOCK_TOKEN_TTL_S,
  };
}

/** The settings of this build. */
export const ENV: AppEnv = readEnv(import.meta.env);

/**
 * The full URL of an API path, for example `apiUrl('/news')` → `/api/news`.
 * The client and the mock handlers both use it, so a path typo fails in
 * tests.
 */
export function apiUrl(path: string, baseUrl = ENV.apiBaseUrl): string {
  return `${baseUrl}${path}`;
}
