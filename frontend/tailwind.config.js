const nativewind = require("nativewind/preset");

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
        background: "#121212",
        surface: "#1E1E1E",
        primary: "#FFDE03",
        accent: "#FFFFFF",
        muted: "#888888",
        "neo-yellow": "#FFDE03",
        "neo-bg": "#121212",
        "neo-text": "#FFFFFF",
      },
      borderWidth: {
        neo: "1px",
      },
      boxShadow: {
        neo: "0px 2px 8px rgba(0,0,0,0.4)",
      },
    },
  },
  plugins: [],
};
