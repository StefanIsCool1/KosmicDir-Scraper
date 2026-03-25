import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'build',
  },
  server: {
    port: 3000,
    proxy: {
      '/scrape': 'http://localhost:5000',
      '/phase2': 'http://localhost:5000',
      '/scraped-sites': 'http://localhost:5000',
    },
  },
})
