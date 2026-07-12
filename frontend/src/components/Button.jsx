import { Link } from 'react-router-dom'

// Two real button styles exist (primary + secondary); ghost is a text link.
// Never use more than two on a single page.
const variants = {
  primary:
    'bg-black text-white hover:bg-[#222222] hover:-translate-y-[2px]',
  secondary:
    'border border-black text-black hover:bg-black hover:text-white',
  ghost:
    'text-black underline-offset-4 hover:underline',
}

const sizes = {
  md: 'px-10 py-4 text-base', // 16px / 40px, per the component spec
  sm: 'px-5 py-2.5 text-sm',
}

export default function Button({ children, variant = 'primary', size = 'md', href, to, className = '', ...props }) {
  const classes = `inline-flex items-center justify-center gap-2 font-medium transition-all duration-200 ${
    variant === 'ghost' ? '' : sizes[size]
  } ${variants[variant]} ${className}`

  if (to) {
    return <Link to={to} className={classes} {...props}>{children}</Link>
  }
  if (href) {
    return <a href={href} className={classes} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>
  }
  return <button className={classes} {...props}>{children}</button>
}
