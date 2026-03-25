import { Link } from 'react-router-dom'

const variants = {
  primary:
    'bg-accent text-white hover:bg-accent-600 shadow-sm',
  secondary:
    'border border-gray-200 text-gray-700 hover:border-gray-300 hover:bg-gray-50',
  ghost:
    'text-gray-500 hover:text-gray-900',
}

export default function Button({ children, variant = 'primary', href, to, className = '', ...props }) {
  const classes = `inline-flex items-center justify-center gap-2 rounded-full px-5 py-2.5 text-sm font-medium transition-all duration-200 ${variants[variant]} ${className}`

  if (to) {
    return <Link to={to} className={classes} {...props}>{children}</Link>
  }
  if (href) {
    return <a href={href} className={classes} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>
  }
  return <button className={classes} {...props}>{children}</button>
}
