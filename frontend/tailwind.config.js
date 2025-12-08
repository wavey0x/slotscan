/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    // Override defaults for consistent sizing
    borderRadius: {
      none: '0',
      DEFAULT: '0',
      sm: '0',
      md: '0',
      lg: '0',
      xl: '0',
      full: '0',
    },
    extend: {
      colors: {
        black: '#000000',
        white: '#FFFFFF',
        gray: {
          100: '#F5F5F5',
          300: '#CCCCCC',
          500: '#666666',
          700: '#333333',
          900: '#111111',
        },
        red: '#CC0000',
        green: '#008800',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Consolas', 'monospace'],
      },
      fontSize: {
        xs: ['11px', { lineHeight: '1.5' }],
        sm: ['13px', { lineHeight: '1.5' }],
        base: ['15px', { lineHeight: '1.5' }],
        lg: ['17px', { lineHeight: '1.2' }],
        xl: ['21px', { lineHeight: '1.2' }],
        '2xl': ['28px', { lineHeight: '1.2' }],
      },
      spacing: {
        '18': '72px',
      },
    },
  },
  plugins: [],
};
