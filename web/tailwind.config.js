/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        // Editorial display — Fraunces with optical-size + soft + wonk axes.
        display: ['Fraunces', 'ui-serif', 'Georgia', 'serif'],
        // Technical body — IBM Plex Sans (precise, characterful).
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        // Numerals + IDs.
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      colors: {
        // Warm paper palette — feels like good newsprint, not SaaS white.
        paper: {
          DEFAULT: '#F5EFE6',
          raised: '#FBF7F0',
          sunken: '#EFE7DA',
        },
        ink: {
          DEFAULT: '#1A1815',
          2: '#4A4540',
          3: '#8A8478',
          4: '#B5AE9F',
        },
        rule: {
          DEFAULT: '#D9CFC0',
          strong: '#A89E8C',
        },
        // Deep oxblood — serious, not festive.
        oxblood: {
          DEFAULT: '#7A1F1F',
          hover: '#5C1717',
          soft: '#E8D7D3',
        },
        ochre: {
          DEFAULT: '#B58E3F',
          soft: '#F0E2C2',
        },
        verdigris: {
          DEFAULT: '#3F6B5C',
          soft: '#D6E5DC',
        },
      },
      letterSpacing: {
        section: '0.18em',
      },
      boxShadow: {
        // Sharp, paper-like shadows — no SaaS-soft glow.
        'paper': '0 1px 0 rgba(26, 24, 21, 0.04), 0 0 0 1px rgba(26, 24, 21, 0.05)',
        'paper-lg': '0 1px 0 rgba(26, 24, 21, 0.06), 0 0 0 1px rgba(26, 24, 21, 0.06), 0 12px 32px -16px rgba(26, 24, 21, 0.18)',
      },
      animation: {
        'fade-up': 'fade-up 600ms cubic-bezier(0.16, 1, 0.3, 1) both',
        'fade-in': 'fade-in 400ms ease-out both',
        'pulse-soft': 'pulse-soft 1.6s ease-in-out infinite',
        'caret': 'caret 1s steps(2, end) infinite',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        'pulse-soft': {
          '0%, 100%': { opacity: '0.4' },
          '50%': { opacity: '1' },
        },
        'caret': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
      },
    },
  },
  plugins: [],
};
