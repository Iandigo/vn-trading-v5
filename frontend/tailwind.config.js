/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0f1117',
        card: '#1e2130',
        border: '#2d3748',
        primary: '#1B6CA8',
        success: '#3BB57A',
        danger: '#E85D24',
        warning: '#f59e0b',
      },
    },
  },
  plugins: [],
}
