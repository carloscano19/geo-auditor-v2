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
        brand: {
          DEFAULT: "var(--brand)",
          lilac: "var(--brand-lilac)",
        },
        night: {
          DEFAULT: "var(--night)",
          2: "var(--night-2)",
        },
        plane: "var(--plane)",
        surface: {
          DEFAULT: "var(--surface)",
          2: "var(--surface-2)",
        },
        hairline: {
          DEFAULT: "var(--hairline)",
          strong: "var(--hairline-strong)",
        },
        ink: {
          DEFAULT: "var(--ink)",
          2: "var(--ink-2)",
          3: "var(--ink-3)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          hover: "var(--accent-hover)",
          on: "var(--accent-on)",
          soft: "var(--accent-soft)",
        },
        verified: "var(--verified)",
        spoofed: {
          DEFAULT: "var(--spoofed)",
          soft: "var(--spoofed-soft)",
        },
        good: {
          DEFAULT: "var(--good)",
          soft: "var(--good-soft)",
        },
        warn: {
          DEFAULT: "var(--warn)",
          soft: "var(--warn-soft)",
        },
        critical: {
          DEFAULT: "var(--critical)",
          soft: "var(--critical-soft)",
        },
        info: {
          DEFAULT: "var(--info)",
          soft: "var(--info-soft)",
        },
        grid: "var(--grid)",
        nav: {
          bg: "var(--nav-bg)",
          ink: "var(--nav-ink)",
          "ink-2": "var(--nav-ink-2)",
          "ink-3": "var(--nav-ink-3)",
          hover: "var(--nav-hover)",
          active: "var(--nav-active)",
          "active-ink": "var(--nav-active-ink)",
          line: "var(--nav-line)",
        },
      },
      borderRadius: {
        card: "16px",
        panel: "16px",
        tile: "12px",
        control: "10px",
      },
      boxShadow: {
        card: "var(--elevation-card)",
        pop: "var(--elevation-pop)",
        banner: "var(--elevation-banner)",
      },
      fontSize: {
        micro: ["0.6875rem", { lineHeight: "1rem" }],
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "-apple-system", "BlinkMacSystemFont", "Inter", "Segoe UI", "sans-serif"],
        display: ["var(--font-display)", "Space Grotesk", "Inter", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
