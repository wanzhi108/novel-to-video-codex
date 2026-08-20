import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // LuminaForge brand palette
        gold: {
          50: "#fefce8",
          100: "#fef9c3",
          200: "#fef08a",
          300: "#fde047",
          400: "#facc15",
          500: "#eab308",
          600: "#ca8a04",
          700: "#a16207",
          800: "#854d0e",
          900: "#713f12",
        },
        ink: {
          50: "#f6f7f9",
          100: "#eceef2",
          200: "#d4d8e0",
          300: "#aeb6c4",
          400: "#818da3",
          500: "#616d85",
          600: "#4d566d",
          700: "#3f475a",
          800: "#363c4b",
          900: "#1a1d26",
          950: "#0d0f15",
        },
      },
      fontFamily: {
        sans: [
          "Noto Sans SC",
          "Source Han Sans SC",
          "Microsoft YaHei",
          "PingFang SC",
          "sans-serif",
        ],
      },
      animation: {
        "fade-in": "fadeIn 0.3s ease-in-out",
        "slide-up": "slideUp 0.3s ease-out",
        "pulse-gold": "pulseGold 2s ease-in-out infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { transform: "translateY(10px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
        pulseGold: {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(234, 179, 8, 0.3)" },
          "50%": { boxShadow: "0 0 0 8px rgba(234, 179, 8, 0)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
