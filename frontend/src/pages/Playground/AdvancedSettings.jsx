import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'

export default function AdvancedSettings({ settings, onChange }) {
  const [open, setOpen] = useState(false)

  const update = (key, value) => onChange({ ...settings, [key]: value })

  return (
    <div className="border-t border-gray-100 pt-4">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between text-sm font-medium text-gray-500 hover:text-gray-700 transition-colors"
      >
        Advanced Settings
        {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {open && (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="text-xs text-gray-400">Proxy Region</span>
            <select
              value={settings.proxyRegion}
              onChange={(e) => update('proxyRegion', e.target.value)}
              className="mt-1 block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
            >
              <option value="auto">Auto</option>
              <option value="us">United States</option>
              <option value="eu">Europe</option>
              <option value="asia">Asia</option>
            </select>
          </label>

          <label className="block">
            <span className="text-xs text-gray-400">Max Pages</span>
            <input
              type="number"
              min={1}
              max={100}
              value={settings.maxPages}
              onChange={(e) => update('maxPages', parseInt(e.target.value) || 1)}
              className="mt-1 block w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
            />
          </label>

          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={settings.jsRendering}
              onChange={(e) => update('jsRendering', e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-accent focus:ring-accent"
            />
            <span className="text-sm text-gray-600">JavaScript rendering</span>
          </label>

          <label className="block">
            <span className="text-xs text-gray-400">Wait time (ms)</span>
            <input
              type="number"
              min={0}
              step={500}
              value={settings.waitTime}
              onChange={(e) => update('waitTime', parseInt(e.target.value) || 0)}
              className="mt-1 block w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 outline-none focus:border-accent focus:ring-1 focus:ring-accent/20"
            />
          </label>
        </div>
      )}
    </div>
  )
}
