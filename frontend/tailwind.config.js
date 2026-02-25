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
        background: "#0B0E14",
        surface: "#171B24",
        primary: "#FFDE03",
        accent: "#FFFFFF",
        muted: "#70778B",
        "neo-yellow": "#FFDE03",
        "neo-bg": "#0B0E14",
        "neo-text": "#FFFFFF",
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
