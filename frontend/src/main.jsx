import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { MotionConfig } from 'framer-motion'
import App from './App'
import Analytics from './pages/Analytics/Analytics'
import { AgentProvider } from './context/AgentContext'
import './index.css'

// One build, two hosts: stats.trawlbase.com serves only the analytics
// dashboard (no router, navbar, or footer — Analytics has no router deps).
// Everything else gets the full app. nginx points both hosts at this bundle.
const isStatsHost = window.location.hostname.startsWith('stats.')

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {isStatsHost ? (
      <Analytics />
    ) : (
      <BrowserRouter>
        {/* reducedMotion="user" honors the OS "Reduce Motion" setting automatically. */}
        <MotionConfig reducedMotion="user">
          {/* Above the router so the Discover chat + live scrape survive header switches.
              App is passed as children (stable ref), so its tree doesn't re-render on
              every streamed message — only the Agent view, which consumes the context. */}
          <AgentProvider>
            <App />
          </AgentProvider>
        </MotionConfig>
      </BrowserRouter>
    )}
  </React.StrictMode>
)
