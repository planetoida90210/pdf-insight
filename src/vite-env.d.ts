/// <reference types="vite/client" />

// Unknown import.meta.env keys are a type error instead of `any`.
interface ViteTypeOptions {
  strictImportMetaEnv: unknown;
}

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
}
