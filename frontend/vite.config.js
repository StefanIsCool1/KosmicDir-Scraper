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
      '/discover': 'http://localhost:5000',
      '/download': 'http://localhost:5000',
      // Analytics: exact-match /a (a prefix would swallow /agent), and only
      // the stats API — /analytics itself is an SPA route in dev.
      '^/a$': 'http://localhost:5000',
      '/analytics/stats': 'http://localhost:5000',
    },
  },
})
