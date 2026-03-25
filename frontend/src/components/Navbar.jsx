import { useState, useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import Button from './Button'
import { NAV_LINKS } from '../lib/constants'

export default function Navbar() {
  const [open, setOpen] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const location = useLocation()

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 10)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => { setOpen(false) }, [location])

  return (
    <nav className={`fixed top-0 left-0 right-0 z-50 transition-all duration-200 ${scrolled ? 'bg-white/80 backdrop-blur-md border-b border-gray-100' : 'bg-white border-b border-transparent'}`}>
      <div className="mx-auto flex max-w-site items-center justify-between px-6 py-4">
        <Link to="/" className="flex items-center gap-1 text-lg">
          <span className="font-bold tracking-tighter text-gray-900">Kosmic</span>
          <span className="font-light text-gray-400">Scraper</span>
        </Link>

        {/* Desktop nav */}
        <div className="hidden items-center gap-8 md:flex">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.label}
              to={link.href}
              className={`text-sm transition-colors ${link.disabled ? 'pointer-events-none text-gray-300' : 'text-gray-500 hover:text-gray-900'}`}
            >
              {link.label}
            </Link>
          ))}
        </div>

        <div className="hidden md:block">
          <Button to="/playground" className="text-xs px-4 py-2">Get Started</Button>
        </div>

        {/* Mobile hamburger */}
        <button onClick={() => setOpen(!open)} className="md:hidden text-gray-600 p-2.5 -mr-2.5" aria-label="Toggle menu">
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile menu */}
      {open && (
        <div className="border-t border-gray-100 bg-white px-6 py-4 md:hidden">
          <div className="flex flex-col gap-3">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.label}
                to={link.href}
                className={`text-sm py-2 ${link.disabled ? 'text-gray-300' : 'text-gray-600'}`}
              >
                {link.label}
              </Link>
            ))}
            <Button to="/playground" className="mt-2 w-full text-center text-xs">Get Started</Button>
          </div>
        </div>
      )}
    </nav>
  )
}
