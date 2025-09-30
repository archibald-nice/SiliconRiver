import type { Config } from "tailwindcss";

export default {
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        river: {
          bg: "#050B1A",
          accent: "#38BDF8",
          highlight: "#F59E0B",
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
