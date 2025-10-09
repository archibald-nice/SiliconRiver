import type { Config } from "tailwindcss";

export default {
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          base: "var(--color-surface-base)",
          raised: "var(--color-surface-raised)",
          overlay: "var(--color-surface-overlay)",
          input: "var(--color-surface-input)",
          chip: "var(--color-surface-chip)",
        },
        border: {
          default: "var(--color-border)",
          strong: "var(--color-border-strong)",
        },
        text: {
          primary: "var(--color-text-primary)",
          secondary: "var(--color-text-secondary)",
          muted: "var(--color-text-muted)",
          inverted: "var(--color-text-inverted)",
        },
        accent: {
          base: "var(--color-accent)",
          contrast: "var(--color-accent-contrast)",
          soft: "var(--color-accent-soft)",
        },
      },
      boxShadow: {
        accent: "0 25px 60px -25px var(--color-shadow-accent)",
      },
    },
  },
  plugins: [],
} satisfies Config;
