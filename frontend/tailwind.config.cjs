/**
 * Brutalist black-and-white design system.
 *
 * The whole app is themed from this file: five inks, zero border-radius,
 * zero shadows. Structure is drawn with 1px hairlines instead of elevation.
 *
 * - `accent` maps to black (the design has no hue), so every existing
 *   accent-* utility resolves into the monochrome system.
 * - gray-* is remapped onto the ink ramp: 900→#000 (primary), 400–700→#555
 *   (secondary, 7.5:1 on white — WCAG AA), 300→#999 (placeholders/disabled
 *   only, never body copy), 100/200→#E5E5E5 (hairlines), 50→#F7F7F7 (surface).
 */

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    // Sharp corners everywhere: every rounded-* utility resolves to 0,
    // including rounded-full (dots and avatars become squares).
    borderRadius: {
      none: '0',
      sm: '0',
      DEFAULT: '0',
      md: '0',
      lg: '0',
      xl: '0',
      '2xl': '0',
      '3xl': '0',
      full: '0',
    },
    // Borders, not elevation. Inline-style shadows (the tour's spotlight
    // mask) are unaffected — that one is functional, not decorative.
    boxShadow: {
      sm: 'none',
      DEFAULT: 'none',
      md: 'none',
      lg: 'none',
      xl: 'none',
      '2xl': 'none',
      inner: 'none',
      none: 'none',
    },
    extend: {
      colors: {
        accent: {
          DEFAULT: '#000000',
          50: '#F7F7F7',
          100: '#E5E5E5',
          200: '#E5E5E5',
          600: '#222222', // primary-button hover
          700: '#000000',
        },
        gray: {
          50: '#F7F7F7',
          100: '#E5E5E5',
          200: '#E5E5E5',
          300: '#999999',
          400: '#555555',
          500: '#555555',
          600: '#555555',
          700: '#555555',
          800: '#222222',
          900: '#000000',
          950: '#000000',
        },
        surface: '#F7F7F7',
        hairline: '#E5E5E5',
      },
      fontFamily: {
        // OS-native faces — no webfont requests at all.
        sans: [
          '"Helvetica Neue"',
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          'Arial',
          'sans-serif',
        ],
        mono: ['ui-monospace', '"SF Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      letterSpacing: {
        tighter: '-0.02em',
      },
      maxWidth: {
        site: '1200px',
      },
    },
  },
  plugins: [],
}
