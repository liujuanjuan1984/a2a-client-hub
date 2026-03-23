const nativewind = require("nativewind/preset");
const { appColors } = require("./theme/colors");

module.exports = {
  content: [
    "./app/**/*.{js,jsx,ts,tsx}",
    "./components/**/*.{js,jsx,ts,tsx}",
    "./hooks/**/*.{js,jsx,ts,tsx}",
    "./screens/**/*.{js,jsx,ts,tsx}",
    "./services/**/*.{js,jsx,ts,tsx}",
    "./store/**/*.{js,jsx,ts,tsx}",
  ],
  presets: [nativewind],
  theme: {
    extend: {
      colors: {
        background: appColors.background,
        surface: appColors.surface,
        primary: appColors.primary,
        accent: appColors.accent,
        muted: appColors.muted,
        "neo-yellow": appColors.neoYellow,
        "neo-green": appColors.neoGreen,
        "neo-bg": appColors.neoBg,
        "neo-text": appColors.neoText,
      },
      borderWidth: {
        neo: "1px",
      },
      boxShadow: {
        neo: "0px 4px 12px rgba(0,0,0,0.5)",
      },
    },
  },
  plugins: [],
};
