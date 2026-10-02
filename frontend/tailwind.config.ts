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
        // LLM Dashboard light theme palette
        background: "#f1f5f9",
        foreground: "#0f172a",
        // Primary brand red accent
        primary: {
          DEFAULT: "#dc2626", // red-600
          hover: "#ef4444",   // red-500
          light: "#fee2e2",   // red-100
          dark: "#b91c1c",    // red-700
        },
        // Score colors (calibrated for light background)
        score: {
          excellent: "#16a34a", // green-600
          good: "#65a30d",      // lime-600
          warning: "#ca8a04",   // amber-600
          poor: "#ea580c",      // orange-600
          critical: "#dc2626",  // red-600
        },
        // Surface colors
        surface: {
          DEFAULT: "#ffffff",
          muted: "#f8fafc",
          hover: "#f1f5f9",
          border: "#e2e8f0",
          elevated: "#ffffff",
        },
        // Text colors
        text: {
          primary: "#0f172a",
          secondary: "#334155",
          muted: "#64748b",
        },
      },
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", "Inter", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Monaco", "Consolas", "JetBrains Mono", "monospace"],
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgba(0, 0, 0, 0.05)",
        card: "0 1px 3px 0 rgba(0, 0, 0, 0.05), 0 1px 2px -1px rgba(0, 0, 0, 0.05)",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.3s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
