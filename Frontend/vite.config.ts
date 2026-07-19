import { defineConfig, ConfigEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }: ConfigEnv) => {
  const isProd = mode === 'production'

  return {
    plugins: [react()],

    build: {
      target: 'esnext',
      minify: isProd ? 'terser' as const : false,
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
            treeshake: 'smallest' as const,
            output: { compact: true }
          }
        : undefined,
      cssMinify: isProd
    }
  }
})
