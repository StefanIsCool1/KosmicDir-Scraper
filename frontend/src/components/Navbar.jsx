import { useState, useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import Button from './Button'
import { NAV_LINKS } from '../lib/constants'

export default function Navbar() {
  const [open, setOpen] = useState(false)
  const location = useLocation()

  useEffect(() => { setOpen(false) }, [location])

  // The full-screen menu is a page of its own — freeze the one behind it.
  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  const isActive = (href) => !href.includes('#') && location.pathname === href

  const linkClasses = (link) => {
    if (link.disabled) return 'pointer-events-none text-gray-300'
    if (isActive(link.href)) return 'text-black underline decoration-2 underline-offset-8'
    return 'text-gray-500 transition-colors hover:text-black'
  }

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 border-b border-hairline bg-white">
      <div className="mx-auto flex max-w-site items-center justify-between px-6 py-4 lg:px-16">
        <Link to="/" className="relative z-50 flex items-center text-lg">
          <span className="font-bold tracking-tighter text-black">Trawl</span>
          <span className="font-normal text-black">base</span>
        </Link>

        {/* Desktop nav */}
        <div className="hidden items-center gap-8 md:flex">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.label}
              to={link.href}
              data-tour={link.label === 'Scraper' ? 'nav-playground' : link.label === 'Discover' ? 'nav-agent' : undefined}
              className={`text-sm ${linkClasses(link)}`}
            >
              {link.label}
            </Link>
          ))}
        </div>

        <div className="hidden md:block">
          <Button to="/playground" size="sm" className="text-xs">Get started</Button>
        </div>

        {/* Mobile hamburger */}
        <button
          onClick={() => setOpen(!open)}
          className="relative z-50 -mr-2.5 p-2.5 text-black md:hidden"
          aria-label={open ? 'Close menu' : 'Open menu'}
          aria-expanded={open}
        >
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile menu: a full-screen overlay, not a drawer. */}
      {open && (
        <div className="fixed inset-0 z-40 flex flex-col bg-white px-6 pt-28 pb-12 md:hidden">
          <div className="flex flex-col gap-8">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.label}
                to={link.href}
                className={`text-3xl font-semibold tracking-tighter ${
                  link.disabled ? 'pointer-events-none text-gray-300' : 'text-black'
                }`}
              >
                {link.label}
              </Link>
            ))}
          </div>
          <div className="mt-auto">
            <Button to="/playground" className="w-full">Get started</Button>
          </div>
        </div>
      )}
    </nav>
  )
}
