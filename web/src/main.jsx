import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { applyTheme, readStored } from "./lib/theme.js";
import "./styles.css";

// Koyu teması seçili olan ilk boyamayı açık görmesin: kök nitelik React render olmadan önce yazılır.
try {
  applyTheme(document, readStored(localStorage));
} catch {
  // Depolama erişilemiyorsa açılış zaten sistem temasındadır.
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
