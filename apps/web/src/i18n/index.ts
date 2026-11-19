import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { en } from "./en";
import { id } from "./id";

export const LANGUAGES = ["en", "id"] as const;
export type Language = (typeof LANGUAGES)[number];
const STORAGE_KEY = "rawibumi.language";

function initialLanguage(): Language {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "id") return saved;
  } catch {
    // Storage can be unavailable (private mode, blocked site data).
  }
  const nav = typeof navigator !== "undefined" ? navigator.languages ?? [navigator.language] : [];
  return nav.some((l) => l?.toLowerCase().startsWith("id")) ? "id" : "en";
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, id: { translation: id } },
  lng: typeof window === "undefined" ? "en" : initialLanguage(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnNull: false
});

if (typeof document !== "undefined") document.documentElement.lang = i18n.language;

export function setLanguage(lang: Language): void {
  void i18n.changeLanguage(lang);
  document.documentElement.lang = lang;
  try {
    window.localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // Preference only; ignore storage failures.
  }
}

export default i18n;
