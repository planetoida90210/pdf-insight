import js from '@eslint/js';
import { defineConfig, globalIgnores } from 'eslint/config';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

export default defineConfig([
  globalIgnores(['dist', 'backend']),
  js.configs.recommended,
  tseslint.configs.strict,
  reactHooks.configs.flat.recommended,
  {
    rules: {
      'react-hooks/exhaustive-deps': 'error',
      'no-console': 'error',
      'no-restricted-properties': [
        'error',
        { object: 'window', property: 'console' },
        { object: 'globalThis', property: 'console' },
      ],
      'no-restricted-syntax': [
        'error',
        {
          selector:
            "JSXAttribute[name.name='dangerouslySetInnerHTML'], Property[key.name='dangerouslySetInnerHTML']",
          message: 'dangerouslySetInnerHTML jest zabronione (brief, sekcja 05).',
        },
      ],
    },
  },
]);
