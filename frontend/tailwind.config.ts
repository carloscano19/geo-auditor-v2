import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Dark mode first palette (Vercel/Stripe inspired)
        background: "#0a0a0a",
        foreground: "#fafafa",
        // Primary accent
        primary: {
          DEFAULT: "#0070f3",
          hover: "#0060df",
          light: "#3291ff",
        },
        // Score colors
        score: {
          excellent: "#22c55e",
          good: "#84cc16",
          warning: "#eab308",
          poor: "#f97316",
          critical: "#ef4444",
        },
        // Surface colors
        surface: {
          DEFAULT: "#111111",
          hover: "#1a1a1a",
          border: "#262626",
          elevated: "#171717",
        },
        // Text colors
        text: {
          primary: "#fafafa",
          secondary: "#a1a1aa",
          muted: "#71717a",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.5s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
