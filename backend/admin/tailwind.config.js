/** Google の管理画面（Material 風）に寄せた配色。色は CSS 変数で持ち、ダークモードも同じ名前で切り替える */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        bg: "rgb(var(--c-bg) / <alpha-value>)",
        surface: "rgb(var(--c-surface) / <alpha-value>)",
        line: "rgb(var(--c-line) / <alpha-value>)",
        ink: "rgb(var(--c-ink) / <alpha-value>)",
        sub: "rgb(var(--c-sub) / <alpha-value>)",
        primary: "rgb(var(--c-primary) / <alpha-value>)",
        "primary-soft": "rgb(var(--c-primary-soft) / <alpha-value>)",
        good: "rgb(var(--c-good) / <alpha-value>)",
        warn: "rgb(var(--c-warn) / <alpha-value>)",
        bad: "rgb(var(--c-bad) / <alpha-value>)",
        "good-soft": "rgb(var(--c-good-soft) / <alpha-value>)",
        "warn-soft": "rgb(var(--c-warn-soft) / <alpha-value>)",
        "bad-soft": "rgb(var(--c-bad-soft) / <alpha-value>)",
      },
      fontFamily: { sans: ['"Google Sans"', "Roboto", "system-ui", '"Hiragino Sans"', '"Noto Sans JP"', "sans-serif"] },
      boxShadow: { card: "0 1px 2px rgb(60 64 67 / .3), 0 1px 3px 1px rgb(60 64 67 / .15)" },
    },
  },
  plugins: [],
};
