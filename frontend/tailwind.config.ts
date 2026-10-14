import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        night: "rgb(16 9 8 / <alpha-value>)",
        umber: "rgb(28 20 16 / <alpha-value>)",
        dusk: "rgb(58 36 24 / <alpha-value>)",
        wine: "rgb(78 18 26 / <alpha-value>)",
        crimson: "rgb(142 30 40 / <alpha-value>)",
        rust: "rgb(182 66 30 / <alpha-value>)",
        ember: "rgb(227 106 46 / <alpha-value>)",
        coral: "rgb(196 69 45 / <alpha-value>)",
        amber: "rgb(240 160 75 / <alpha-value>)",
        peach: "rgb(244 184 128 / <alpha-value>)",
        ivory: "rgb(247 241 234 / <alpha-value>)",
        mist: "rgb(205 190 174 / <alpha-value>)",
        panel: "rgb(36 24 18 / <alpha-value>)",
        raised: "rgb(52 40 32 / <alpha-value>)",
        line: "rgb(247 241 234 / 0.16)",
        action: "rgb(200 60 40 / <alpha-value>)",
        celadon: "rgb(155 196 154 / <alpha-value>)",
      },
      fontFamily: {
        sans: ["var(--font-ui)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Georgia", "ui-serif", "serif"],
      },
      borderRadius: {
        card: "18px",
        control: "10px",
      },
      boxShadow: {
        lift: "0 30px 80px rgb(16 9 8 / 0.55)",
      },
      blur: {
        atmosphere: "80px",
      },
    },
  },
  plugins: [],
};

export default config;
