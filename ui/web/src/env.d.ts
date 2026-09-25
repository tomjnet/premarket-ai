/// <reference types="vite/client" />

/** The `VITE_*` variables the app reads (see `.env.example`). */
interface ImportMetaEnv {
  /** `mock` or `live`; validated by `readEnv` in src/lib/env.ts. */
  readonly VITE_API_MODE?: string;
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_MOCK_TOKEN_TTL_S?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
