/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["selector", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Alle Farben hängen an CSS-Custom-Properties (siehe index.css) — so
        // greift der Dark/Light-Wechsel automatisch in jeder Utility-Klasse.
        bg: "var(--bg)",
        bg2: "var(--inset)",
        "bg-glow": "var(--bg-glow)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        "surface-3": "var(--surface-3)",
        inset: "var(--inset)",
        // Aliase auf das alte Namensschema, damit bestehende Klassen weiterleben.
        panel: "var(--surface)",
        panel2: "var(--surface-2)",
        line: "var(--border)",
        line2: "var(--border-strong)",
        txt: "var(--text)",
        muted: "var(--muted)",
        faint: "var(--faint)",
        accent: "var(--accent)",
        "accent-ink": "var(--accent-ink)",
        // Rarity-Palette.
        common: "var(--r-common)",
        uncommon: "var(--r-uncommon)",
        rare: "var(--r-rare)",
        epic: "var(--r-epic)",
        legendary: "var(--r-legendary)",
        mythic: "var(--r-mythic)",
        danger: "var(--r-mythic)",
        // violet = epic-Akzent (lila). Numerische Stufen für Alt-Referenzen.
        violet: {
          DEFAULT: "var(--r-epic)",
          100: "color-mix(in oklab, var(--r-epic) 22%, var(--text))",
          200: "color-mix(in oklab, var(--r-epic) 40%, var(--text))",
          400: "color-mix(in oklab, var(--r-epic) 70%, var(--text))",
          500: "color-mix(in oklab, var(--r-epic) 85%, transparent)",
          600: "var(--r-epic)",
        },
      },
      fontFamily: {
        sans: ['"Hanken Grotesk"', "system-ui", "sans-serif"],
        display: ['"Space Grotesk"', '"Hanken Grotesk"', "sans-serif"],
        mono: ['"JetBrains Mono"', "monospace"],
      },
      borderRadius: {
        sm: "var(--r-sm)",
        md: "var(--r-md)",
        lg: "var(--r-lg)",
        xl: "var(--r-md)",
        "2xl": "var(--r-md)",
        "3xl": "var(--r-lg)",
      },
      boxShadow: {
        glow: "var(--shadow)",
        "glow-lime": "0 0 24px color-mix(in oklab, var(--accent) 32%, transparent)",
        "glow-violet": "0 0 28px color-mix(in oklab, var(--r-epic) 32%, transparent)",
        "inset-soft": "inset 0 1px 0 rgba(255,255,255,0.04)",
      },
      transitionTimingFunction: {
        smooth: "cubic-bezier(.22,.61,.36,1)",
      },
      keyframes: {
        aurora: {
          "0%": { backgroundPosition: "50% 50%, 50% 50%" },
          "100%": { backgroundPosition: "350% 50%, 350% 50%" },
        },
        rise: {
          from: { opacity: "0", transform: "translateY(16px)" },
          to: { opacity: "1", transform: "none" },
        },
        "spin-slow": {
          to: { transform: "rotate(360deg)" },
        },
        "xp-shine": {
          "0%": { transform: "translateX(-100%)" },
          "60%,100%": { transform: "translateX(220%)" },
        },
        "toast-in": {
          from: { opacity: "0", transform: "translateY(14px) scale(.96)" },
          to: { opacity: "1", transform: "none" },
        },
      },
      animation: {
        aurora: "aurora 60s linear infinite",
        rise: "rise 0.5s cubic-bezier(.22,.61,.36,1) both",
        "spin-slow": "spin-slow 1s linear infinite",
        "xp-shine": "xp-shine 2.4s ease-in-out infinite",
        "toast-in": "toast-in 0.35s cubic-bezier(.22,.61,.36,1)",
      },
    },
  },
  plugins: [],
};
