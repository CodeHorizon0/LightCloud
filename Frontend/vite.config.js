import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(function ({ mode }) {
  const isProd = mode === 'production'

  return {
    plugins: [react()],

    build: {
      target: 'esnext',
      minify: isProd ? 'terser' : false,
      esbuild: {
        supported: { var: false }
      },
      terserOptions: isProd
        ? {
            compress: {
              drop_console: true,
              drop_debugger: true
            },
            format: { comments: false }
          }
        : undefined,
      rollupOptions: isProd
        ? {
            treeshake: 'smallest',
            output: { compact: true }
          }
        : undefined,
      cssMinify: isProd
    }
  }
})
