/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: "#003580",
          50: "#eff6ff",
          500: "#3b82f6",
          600: "#003580",
          700: "#002760",
          900: "#001a40",
        },
      },
    },
  },
  plugins: [],
};
