import type { Config } from "tailwindcss";

/**
 * Colour system (30-60-10 rule)
 * ---------------------------------------------------------------
 * 60% - neutral surfaces: white cards on a slate canvas, plus text.
 * 30% - "water" blue: the primary hue, used for navigation, primary
 *       actions and data series.  Deep enough to read as professional.
 * 10% - "signal" amber: reserved for the single most important action or
 *       attention state on a screen (active nav marker, focus, warnings).
 *
 * All foreground/background pairs below meet WCAG AA (>= 4.5:1) for body
 * text; the amber accent is only ever used with dark text on light amber, or
 * as a non-text marker.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Neutral canvas / surfaces (the 60%).
        canvas: "#f6f7f9",
        surface: "#ffffff",
        border: "#e2e5ea",
        muted: "#6b7280",
        ink: "#111827",
        "ink-soft": "#374151",

        // Primary hue (the 30%).
        water: {
          50: "#f0f6fb",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#1d5fa8",
          700: "#17497f",
          800: "#123a66",
          900: "#0d2b4c",
        },

        // Accent (the 10%) - light amber with dark ink for AA contrast.
        signal: {
          50: "#fff8eb",
          100: "#fdecc8",
          200: "#f8d894",
          300: "#eec25b",
          400: "#e0a832",
          500: "#c8891a",
          600: "#9a6813",
          700: "#6f4b10",
        },

        // Semantic status colours, used for quality flags and outcomes only.
        success: { light: "#e7f6ec", DEFAULT: "#1f7a3d", dark: "#155c2c" },
        warning: { light: "#fdf3e0", DEFAULT: "#a86414", dark: "#7d4a0f" },
        danger: { light: "#fdecea", DEFAULT: "#b3261e", dark: "#8a1d17" },
        info: { light: "#eaf2fb", DEFAULT: "#1d5fa8", dark: "#17497f" },
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Consolas", "monospace"],
      },
      borderRadius: {
        card: "0.625rem",
      },
      boxShadow: {
        card: "0 1px 2px rgba(17, 24, 39, 0.04), 0 1px 3px rgba(17, 24, 39, 0.06)",
        pop: "0 8px 24px rgba(17, 24, 39, 0.12)",
      },
    },
  },
  plugins: [],
} satisfies Config;
