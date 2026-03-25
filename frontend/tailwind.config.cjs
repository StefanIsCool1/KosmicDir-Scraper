const defaultTheme = require('tailwindcss/defaultTheme')

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: '#6C5CE7',
          50: '#F0EEFF',
          100: '#DDD8FC',
          200: '#B8AFF7',
          600: '#5A4BD4',
          700: '#4A3DB8',
        },
      },
      fontFamily: {
        sans: ['"General Sans"', ...defaultTheme.fontFamily.sans],
        mono: ['"JetBrains Mono"', ...defaultTheme.fontFamily.mono],
      },
      letterSpacing: {
        tighter: '-0.02em',
      },
      borderRadius: {
        xl: '12px',
      },
      maxWidth: {
        site: '1200px',
      },
    },
  },
  plugins: [],
}
