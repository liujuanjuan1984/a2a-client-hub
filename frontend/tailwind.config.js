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
        background: "#05070a",
        surface: "#0f1218",
        primary: "#5c6afb",
        accent: "#ffb347",
        muted: "#6b7280",
        "neo-yellow": "#FFDE03",
        "neo-bg": "#F5F5F5",
        "neo-text": "#000000",
      },
      borderWidth: {
        neo: "2px",
      },
      boxShadow: {
        neo: "4px 4px 0px 0px rgba(0,0,0,1)",
      },
    },
  },
  plugins: [],
};
