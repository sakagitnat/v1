/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        grove: {
          50: "#f2f8f0",
          100: "#e1eedb",
          200: "#c2ddb7",
          300: "#9cc78b",
          400: "#73ac5f",
          500: "#548e42",
          600: "#3f7132",
          700: "#33592a",
          800: "#2b4824",
          900: "#243c1f",
        },
      },
    },
  },
  plugins: [],
};
