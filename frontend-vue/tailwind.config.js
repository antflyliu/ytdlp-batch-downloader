/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Override Tailwind gray → Claude warm palette
        gray: {
          50: '#faf9f5',  // Ivory
          100: '#f5f4ed', // Parchment
          200: '#f0eee6', // Border Cream
          300: '#e8e6dc', // Warm Sand / Border Warm
          400: '#d1cfc5', // Ring Warm
          500: '#b0aea5', // Warm Silver
          600: '#87867f', // Stone Gray
          700: '#5e5d59', // Olive Gray
          800: '#4d4c48', // Charcoal Warm
          900: '#141413', // Near Black
          950: '#0d0d0c',
        },
        // Claude brand tokens as Tailwind colors
        terracotta: {
          DEFAULT: '#c96442',
          hover: '#d97757',
          pressed: '#b95738',
          dim: 'rgba(201,100,66,0.12)',
          ring: 'rgba(201,100,66,0.30)',
        },
        parchment:  '#f5f4ed',
        ivory:      '#faf9f5',
        'border-cream': '#f0eee6',
        'warm-sand': '#e8e6dc',
        'stone-gray': '#87867f',
        'olive-gray': '#5e5d59',
        'charcoal-warm': '#4d4c48',
        'near-black': '#141413',
      },
    },
  },
  plugins: [],
}