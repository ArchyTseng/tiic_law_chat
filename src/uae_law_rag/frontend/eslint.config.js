import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default defineConfig([
  globalIgnores(['dist']),

  // Base rules (unchanged)
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },

  // ---------------------------------------------------------------------------
  // Import boundary enforcement (M1 minimal viable)
  // ---------------------------------------------------------------------------

  // 1) Pages must not import API or HTTP DTOs directly
  {
    files: ['src/pages/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/api/*', '@/api/**'],
              message: 'Pages must not call api directly. Use services -> stores -> pages flow.',
            },
            {
              group: ['@/types/http/*', '@/types/http/**'],
              message: 'Pages must not import HTTP DTOs. Use domain/ui types only.',
            },
          ],
        },
      ],
    },
  },

  // 2) Stores must not import API or HTTP DTOs
  {
    files: ['src/stores/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/api/*', '@/api/**'],
              message: 'Stores must not import api. Use services as the only integration point.',
            },
            {
              group: ['@/types/http/*', '@/types/http/**'],
              message: 'Stores must not import HTTP DTOs. Store state should be domain/ui types only.',
            },
          ],
        },
      ],
    },
  },

  // 3) API layer must not import domain/ui/stores/pages/services
  {
    files: ['src/api/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/types/domain/*', '@/types/domain/**', '@/types/ui/*', '@/types/ui/**'],
              message: 'API layer must not import domain/ui types. Use types/http DTO only.',
            },
            {
              group: ['@/stores/*', '@/stores/**', '@/pages/*', '@/pages/**', '@/services/*', '@/services/**'],
              message: 'API layer must not import stores/pages/services.',
            },
          ],
        },
      ],
    },
  },

  // 4) Types must be pure (no runtime module imports)
  {
    files: ['src/types/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: [
                '@/api/*',
                '@/api/**',
                '@/services/*',
                '@/services/**',
                '@/stores/*',
                '@/stores/**',
                '@/pages/*',
                '@/pages/**',
                '@/ui/*',
                '@/ui/**',
                '@/utils/*',
                '@/utils/**',
              ],
              message: 'Types layer must be pure. Do not import runtime modules into types.',
            },
          ],
        },
      ],
    },
  },

  // 5) UI must be presentation-only (no api/services/stores, no HTTP DTOs)
  {
    files: ['src/ui/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/api/*', '@/api/**', '@/services/*', '@/services/**', '@/stores/*', '@/stores/**'],
              message: 'UI layer must not import api/services/stores. Keep UI components presentation-only.',
            },
            {
              group: ['@/types/http/*', '@/types/http/**'],
              message: 'UI layer must not import HTTP DTOs. Use domain/ui view types only.',
            },
          ],
        },
      ],
    },
  },

  // 6) Utils must not import higher layers
  {
    files: ['src/utils/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/api/*', '@/api/**', '@/services/*', '@/services/**', '@/stores/*', '@/stores/**', '@/pages/*', '@/pages/**'],
              message: 'Utils must not import api/services/stores/pages. Keep utils as pure helpers.',
            },
          ],
        },
      ],
    },
  },
  // ---------------------------------------------------------------------------
  // Import boundary enforcement (Enhanced)
  // ---------------------------------------------------------------------------

  // 7) Services: must not depend on pages/stores/ui (keep services pure integration+normalize)
  {
    files: ['src/services/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/pages/*', '@/pages/**'],
              message: 'Services must not import pages. Keep UI composition in pages layer.',
            },
            {
              group: ['@/stores/*', '@/stores/**'],
              message: 'Services must not import stores. Services return domain/ui types to stores.',
            },
            {
              group: ['@/ui/*', '@/ui/**'],
              message: 'Services must not import ui. UI should consume service outputs, not vice versa.',
            },
          ],
        },
      ],
    },
  },

  // 8) Endpoints: only transport layer (api/http + types/http + utils optional)
  {
    files: ['src/api/endpoints/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/types/domain/*', '@/types/domain/**', '@/types/ui/*', '@/types/ui/**'],
              message: 'Endpoints must not import domain/ui. Endpoints are DTO-only.',
            },
            {
              group: ['@/services/*', '@/services/**', '@/stores/*', '@/stores/**', '@/pages/*', '@/pages/**'],
              message: 'Endpoints must not import services/stores/pages. Keep endpoints transport-only.',
            },
          ],
        },
      ],
    },
  },

  // 9) Pages child components: enforce container/presentational split
  // Components under pages/**/components should not read stores directly (ChatPage is the container).
  {
    files: ['src/pages/**/components/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/stores/*', '@/stores/**'],
              message:
                'Page components must not import stores directly. Pass state/actions via props from the page container.',
            },
            {
              group: ['@/api/*', '@/api/**'],
              message: 'Page components must not import api. Use services/stores via the page container.',
            },
            {
              group: ['@/types/http/*', '@/types/http/**'],
              message: 'Page components must not import HTTP DTOs. Use domain/ui view types only.',
            },
          ],
        },
      ],
    },
  },

  // 10) App layer: allow routes to reference pages, but prevent api usage in app shell/providers
  // - routes.tsx is allowed to import pages.
  // - other app files must not import api directly.
  {
    files: ['src/app/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/api/*', '@/api/**'],
              message:
                'App layer must not import api directly. Keep data fetching in services/stores/pages, not app shell/providers.',
            },
          ],
        },
      ],
    },
  },
  {
    files: ['src/app/routes.tsx'],
    rules: {
      // routes.tsx may import pages for routing composition
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            // still forbid api and HTTP DTOs even in routes
            {
              group: ['@/api/*', '@/api/**'],
              message: 'Routes must not import api.',
            },
            {
              group: ['@/types/http/*', '@/types/http/**'],
              message: 'Routes must not import HTTP DTOs.',
            },
          ],
        },
      ],
    },
  },
])
