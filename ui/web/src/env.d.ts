/// <reference types="vite/client" />

/** The `VITE_*` variables the app reads (see `.env.example`). */
interface ImportMetaEnv {
  readonly VITE_API_MODE?: 'mock' | 'live';
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_MOCK_TOKEN_TTL_S?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
