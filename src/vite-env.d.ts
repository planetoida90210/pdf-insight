/// <reference types="vite/client" />

// Nieznane klucze import.meta.env są błędem typów zamiast `any`.
interface ViteTypeOptions {
  strictImportMetaEnv: unknown;
}

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
}
