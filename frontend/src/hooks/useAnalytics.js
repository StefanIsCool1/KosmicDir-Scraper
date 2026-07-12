import { useEffect, useRef, useCallback } from 'react'
import { useLocation } from 'react-router-dom'

const STORAGE_KEY = 'twl_vid'

function getVisitorId() {
  try {
    let id = localStorage.getItem(STORAGE_KEY)
    if (!id) {
      id = crypto.randomUUID()
      localStorage.setItem(STORAGE_KEY, id)
    }
    return id
  } catch {
    return crypto.randomUUID()
  }
}

function post(path, body) {
  try {
    fetch('/a', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      keepalive: true,
    }).catch(() => {})
  } catch {
    // silently ignore
  }
}

const _visitorId = getVisitorId()  // module-level — shared by all callers

/**
 * useAnalytics — self-hosted, zero-fuzz page-view + event tracking.
 *
 * Call with { trackPageViews: true } in App.jsx to fire page_view events
 * on every route change.  Everywhere else, call without args to get a
 * trackEvent function that shares the same persistent visitor ID.
 */
export default function useAnalytics({ trackPageViews = false } = {}) {
  const location = useLocation()
  const prevPath = useRef(null)

  // Page-view tracking — fires only when opted in
  useEffect(() => {
    if (!trackPageViews) return

    const path = location.pathname
    if (path === prevPath.current) return
    prevPath.current = path

    post(path, {
      visitor_id: _visitorId,
      type: 'page_view',
      path,
      referrer: document.referrer || '',
    })
  }, [location.pathname, trackPageViews])

  const trackEvent = useCallback((eventName, eventData = {}) => {
    post(location.pathname, {
      visitor_id: _visitorId,
      type: 'event',
      event_name: eventName,
      event_data: eventData,
      path: location.pathname,
    })
  }, [location.pathname])

  return { trackEvent, visitorId: _visitorId }
}
