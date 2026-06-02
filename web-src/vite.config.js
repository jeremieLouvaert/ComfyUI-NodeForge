import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import cssInjectedByJs from 'vite-plugin-css-injected-by-js'

export default defineConfig({
  plugins: [
    react(),
    cssInjectedByJs(),
  ],
  build: {
    outDir: '../web',
    emptyOutDir: false,
    cssCodeSplit: false,
    rollupOptions: {
      input: 'src/main.jsx',
      external: ['/scripts/app.js', '/scripts/api.js'],
      output: {
        entryFileNames: 'nodeforge.js',
        chunkFileNames: 'nodeforge-[hash].js',
        inlineDynamicImports: true,
        manualChunks: undefined,
        format: 'es',
      },
    },
  },
})
