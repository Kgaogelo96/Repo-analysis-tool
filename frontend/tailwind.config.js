/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#0f172a', // app background
          raised: '#1e293b', // cards / panels
          border: '#334155', // separators
        },
      },
    },
  },
  plugins: [],
}
