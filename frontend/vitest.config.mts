import { defineConfig } from 'vitest/config'
import path from 'path'

export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
    globals: true,
    // lalapp-hook: upstream's tests cover upstream behavior; Lalapp tests enable features explicitly.
    env: {
      NEXT_PUBLIC_LALAPP_PLACEMENT: 'false',
      NEXT_PUBLIC_LALAPP_PERSONAS: 'false',
      NEXT_PUBLIC_LALAPP_ADAPTIVE: 'false',
      NEXT_PUBLIC_LALAPP_SCENARIOS: 'false',
      NEXT_PUBLIC_LALAPP_RHYTHM: 'false',
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
})
