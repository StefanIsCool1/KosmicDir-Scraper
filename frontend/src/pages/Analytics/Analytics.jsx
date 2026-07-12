import { useState, useEffect, useCallback } from 'react'
import { Lock, Eye, Users, MousePointerClick, Activity, BarChart3 } from 'lucide-react'

const SESSION_KEY = 'twl_analytics_auth'

function loadPassword() {
  try { return sessionStorage.getItem(SESSION_KEY) || '' } catch { return '' }
}
function savePassword(pw) {
  try { sessionStorage.setItem(SESSION_KEY, pw) } catch { /* ignore */ }
}
function clearPassword() {
  try { sessionStorage.removeItem(SESSION_KEY) } catch { /* ignore */ }
}

export default function Analytics() {
  const [password, setPassword] = useState(loadPassword)
  const [pwInput, setPwInput] = useState('')
  const [authenticated, setAuthenticated] = useState(!!loadPassword())
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [days, setDays] = useState(30)

  const fetchStats = useCallback(async (pw, d) => {
    setLoading(true)
    setError('')
    try {
      const resp = await fetch(`/analytics/stats?password=${encodeURIComponent(pw)}&days=${d}`)
      if (resp.status === 401) {
        setError('Wrong password')
        setAuthenticated(false)
        clearPassword()
        setStats(null)
        return
      }
      if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`)
      const data = await resp.json()
      setStats(data)
      setAuthenticated(true)
      savePassword(pw)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  // Auto-fetch on mount if already authenticated
  useEffect(() => {
    const pw = loadPassword()
    if (pw) fetchStats(pw, days)
  }, [days])

  const handleLogin = (e) => {
    e.preventDefault()
    if (!pwInput.trim()) return
    fetchStats(pwInput.trim(), days)
    setPassword(pwInput.trim())
  }

  const handleLogout = () => {
    clearPassword()
    setAuthenticated(false)
    setStats(null)
    setPassword('')
    setPwInput('')
  }

  // --- Login screen ---
  if (!authenticated || !stats) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white pt-20">
        <div className="w-full max-w-sm px-6">
          <div className="mb-8 text-center">
            <Lock size={32} className="mx-auto mb-3 text-gray-300" />
            <h1 className="text-xl font-bold tracking-tighter text-black">Analytics</h1>
            <p className="mt-1 text-sm text-gray-500">Enter the analytics password to continue.</p>
          </div>
          <form onSubmit={handleLogin} className="space-y-3">
            <input
              type="password"
              value={pwInput}
              onChange={(e) => setPwInput(e.target.value)}
              placeholder="Password"
              autoFocus
              className="w-full border border-hairline bg-white px-4 py-2.5 text-sm text-black placeholder-gray-400 outline-none focus:border-black"
            />
            {error && <p className="text-xs text-red-500">{error}</p>}
            <button
              type="submit"
              disabled={loading || !pwInput.trim()}
              className="w-full bg-black py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {loading ? 'Loading...' : 'View stats'}
            </button>
          </form>
        </div>
      </div>
    )
  }

  // --- Dashboard ---
  const StatCard = ({ icon: Icon, label, value, sub }) => (
    <div className="border border-hairline bg-white p-5">
      <div className="flex items-center gap-2 text-gray-400">
        <Icon size={16} />
        <span className="text-[11px] font-medium uppercase tracking-wider">{label}</span>
      </div>
      <div className="mt-2 text-3xl font-bold tracking-tighter text-black">{value}</div>
      {sub && <div className="mt-1 text-xs text-gray-400">{sub}</div>}
    </div>
  )

  // Build a simple daily bar chart using divs (no chart library needed)
  const maxDailyPV = Math.max(1, ...(stats.daily_page_views || []).map((d) => d.count))
  const maxDailyEV = Math.max(1, ...(stats.daily_events || []).map((d) => d.count))
  const hasData = stats.total_page_views > 0 || stats.total_events > 0

  return (
    <div className="min-h-screen bg-white pt-20">
      <div className="mx-auto max-w-site px-6 py-12">
        {/* Header */}
        <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tighter text-black">Analytics</h1>
            <p className="mt-1 text-sm text-gray-500">
              Last {stats.period_days} days · generated {new Date(stats.generated_at).toLocaleString()}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="border border-hairline bg-white px-3 py-2 text-xs text-gray-600 outline-none"
            >
              <option value={7}>7 days</option>
              <option value={30}>30 days</option>
              <option value={90}>90 days</option>
              <option value={365}>1 year</option>
            </select>
            <button
              onClick={() => fetchStats(password, days)}
              disabled={loading}
              className="border border-hairline px-3 py-2 text-xs text-gray-500 transition-colors hover:border-black hover:text-black"
            >
              {loading ? 'Refreshing...' : 'Refresh'}
            </button>
            <button
              onClick={handleLogout}
              className="text-xs text-gray-400 transition-colors hover:text-red-500"
            >
              Lock
            </button>
          </div>
        </div>

        {!hasData ? (
          <div className="border border-hairline bg-surface p-16 text-center">
            <BarChart3 size={40} className="mx-auto mb-3 text-gray-200" />
            <p className="text-sm text-gray-400">No data yet. Visitors will show up here once they start browsing.</p>
          </div>
        ) : (
          <>
            {/* --- Key metrics --- */}
            <div className="mb-10 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatCard icon={Eye} label="Page Views" value={stats.total_page_views.toLocaleString()} />
              <StatCard icon={Users} label="Unique Visitors" value={stats.unique_visitors.toLocaleString()} />
              <StatCard icon={MousePointerClick} label="Events" value={stats.total_events.toLocaleString()} />
              <StatCard icon={Activity} label="Avg Views / Visitor" value={
                stats.unique_visitors > 0
                  ? (stats.total_page_views / stats.unique_visitors).toFixed(1)
                  : '0'
              } />
            </div>

            {/* --- Page views by path --- */}
            <div className="mb-10">
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">
                Page Views by Page
              </h2>
              <div className="border border-hairline">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-hairline bg-surface text-xs uppercase tracking-wider text-gray-500">
                      <th className="px-4 py-3 font-medium">Path</th>
                      <th className="px-4 py-3 text-right font-medium">Views</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(stats.page_views_by_path).map(([path, count]) => (
                      <tr key={path} className="border-b border-hairline last:border-0">
                        <td className="px-4 py-2.5 font-mono text-xs text-black">{path}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-gray-600">{count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* --- Events by name --- */}
            <div className="mb-10">
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">
                Actions
              </h2>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(stats.events_by_name).map(([name, data]) => (
                  <div key={name} className="border border-hairline p-4">
                    <div className="font-mono text-xs text-black">{name}</div>
                    <div className="mt-1 flex items-baseline gap-3">
                      <span className="text-2xl font-bold tracking-tighter text-black">{data.total}</span>
                      <span className="text-xs text-gray-400">{data.unique_visitors} unique</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* --- Daily chart --- */}
            <div className="mb-10">
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">
                Daily Page Views
              </h2>
              <div className="border border-hairline p-6">
                <div className="flex items-end gap-[2px]" style={{ height: 120 }}>
                  {(stats.daily_page_views || []).map((d) => (
                    <div
                      key={d.date}
                      className="flex-1 bg-black transition-opacity hover:opacity-70"
                      style={{ height: `${(d.count / maxDailyPV) * 100}%`, minHeight: d.count > 0 ? 3 : 0 }}
                      title={`${d.date}: ${d.count} views`}
                    />
                  ))}
                </div>
                <div className="mt-2 flex justify-between text-[10px] text-gray-400">
                  <span>{(stats.daily_page_views || [])[0]?.date}</span>
                  <span>{(stats.daily_page_views || []).slice(-1)[0]?.date}</span>
                </div>
              </div>
            </div>

            {/* --- Daily events --- */}
            <div className="mb-10">
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">
                Daily Actions
              </h2>
              <div className="border border-hairline p-6">
                <div className="flex items-end gap-[2px]" style={{ height: 120 }}>
                  {(stats.daily_events || []).map((d) => (
                    <div
                      key={d.date}
                      className="flex-1 bg-black transition-opacity hover:opacity-70"
                      style={{ height: `${(d.count / maxDailyEV) * 100}%`, minHeight: d.count > 0 ? 3 : 0 }}
                      title={`${d.date}: ${d.count} events`}
                    />
                  ))}
                </div>
                <div className="mt-2 flex justify-between text-[10px] text-gray-400">
                  <span>{(stats.daily_events || [])[0]?.date}</span>
                  <span>{(stats.daily_events || []).slice(-1)[0]?.date}</span>
                </div>
              </div>
            </div>

            {/* --- Recent visitors --- */}
            <div>
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">
                Recent Visitors
              </h2>
              <div className="border border-hairline">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-hairline bg-surface text-xs uppercase tracking-wider text-gray-500">
                      <th className="px-4 py-3 font-medium">Visitor</th>
                      <th className="px-4 py-3 text-right font-medium">Last Seen</th>
                      <th className="px-4 py-3 text-right font-medium">Page Views</th>
                      <th className="px-4 py-3 text-right font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(stats.recent_visitors || []).slice(0, 20).map((v) => (
                      <tr key={v.visitor_id} className="border-b border-hairline last:border-0">
                        <td className="px-4 py-2.5 font-mono text-[10px] text-gray-500">{v.visitor_id}</td>
                        <td className="px-4 py-2.5 text-right text-xs text-gray-500">
                          {new Date(v.last_seen).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-gray-600">{v.page_views}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums text-gray-600">{v.events}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
