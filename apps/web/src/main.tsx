import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Interface font: Archivo, with Archivo Narrow for dense tables (ADR 0011).
import "@fontsource/archivo/400.css";
import "@fontsource/archivo/500.css";
import "@fontsource/archivo/600.css";
import "@fontsource/archivo-narrow/400.css";
import "@fontsource/archivo-narrow/500.css";
import "@fontsource/archivo-narrow/600.css";
// IDs and the wordmark.
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/michroma/400.css";
import "./i18n";
import App from "./App";
import "./ui/tokens.css";
import "./ui/fonts.css";
import "./styles.css";


createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
