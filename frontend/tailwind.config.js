/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        // VIETRAVEL BLUE — Primary brand color (logo background)
        primary: {
          DEFAULT: "#0033A0",
          50: "#EFF3FF",
          100: "#DCE5FB",
          200: "#B9CBF6",
          300: "#8AA8EE",
          400: "#5680E2",
          500: "#2E5DD2",
          600: "#0033A0",
          700: "#002A85",
          800: "#001F66",
          900: "#001448",
        },
        // VIETRAVEL RED — Accent (chấm trên chữ "i" + critical alerts)
        accent: {
          DEFAULT: "#E30613",
          50: "#FFF1F2",
          100: "#FFE4E6",
          400: "#F2384B",
          500: "#E30613",
          600: "#C70511",
          700: "#A0040E",
        },
        // Brand-aware semantic colors
        brand: {
          blue: "#0033A0",
          red: "#E30613",
          "blue-deep": "#001448",
          "blue-soft": "#EFF3FF",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      boxShadow: {
        // Brand-tinted shadows (Vietravel blue)
        glow: "0 0 0 1px rgba(0,51,160,0.15), 0 8px 30px -8px rgba(0,51,160,0.45)",
        "card-hover": "0 12px 32px -12px rgba(0,51,160,0.25)",
        "brand-sm": "0 1px 3px rgba(0,51,160,0.10)",
        "brand-md": "0 4px 6px rgba(0,51,160,0.10)",
        "brand-lg": "0 10px 15px rgba(0,51,160,0.12)",
        "brand-xl": "0 20px 25px rgba(0,51,160,0.15)",
        "accent-glow": "0 0 0 3px rgba(227,6,19,0.15)",
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        // 100% dùng transform:none (không phải translateY(0)/scale(1)) — fill 'both' giữ
        // frame cuối; nếu giữ 1 transform value sẽ tạo containing block khiến mọi modal
        // position:fixed bên trong bị lệch khỏi giữa màn hình. 'none' = hết containing block.
        "fade-in-up": {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "none" },
        },
        "fade-in-down": {
          "0%": { opacity: "0", transform: "translateY(-12px)" },
          "100%": { opacity: "1", transform: "none" },
        },
        "scale-in": {
          "0%": { opacity: "0", transform: "scale(0.96)" },
          "100%": { opacity: "1", transform: "none" },
        },
        "slide-in-left": {
          "0%": { opacity: "0", transform: "translateX(-16px)" },
          "100%": { opacity: "1", transform: "none" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-12px)" },
        },
        "float-slow": {
          "0%, 100%": { transform: "translateY(0) translateX(0)" },
          "50%": { transform: "translateY(-22px) translateX(10px)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
        "gradient-shift": {
          "0%, 100%": { "background-position": "0% 50%" },
          "50%": { "background-position": "100% 50%" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
        "spin-slow": {
          to: { transform: "rotate(360deg)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.4s ease-out both",
        "fade-in-up": "fade-in-up 0.5s cubic-bezier(0.22,1,0.36,1) both",
        "fade-in-down": "fade-in-down 0.5s cubic-bezier(0.22,1,0.36,1) both",
        "scale-in": "scale-in 0.4s cubic-bezier(0.22,1,0.36,1) both",
        "slide-in-left": "slide-in-left 0.4s cubic-bezier(0.22,1,0.36,1) both",
        float: "float 6s ease-in-out infinite",
        "float-slow": "float-slow 9s ease-in-out infinite",
        "gradient-shift": "gradient-shift 12s ease infinite",
        "pulse-soft": "pulse-soft 1.6s ease-in-out infinite",
        "spin-slow": "spin-slow 1s linear infinite",
      },
    },
  },
  plugins: [],
};
