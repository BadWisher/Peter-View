const KEY = "pv-lang";
let dict = {};
let locale = "ru";

function readStored() {
  try {
    const value = localStorage.getItem(KEY);
    return value === "en" || value === "ru" ? value : "ru";
  } catch {
    return "ru";
  }
}

export function currentLocale() {
  return locale;
}

export function t(key) {
  return key.split(".").reduce((node, part) => (node && node[part] != null ? node[part] : undefined), dict) ?? key;
}

export async function loadLocale(lang = readStored()) {
  locale = lang === "en" ? "en" : "ru";
  const response = await fetch(`i18n/${locale}.json`);
  dict = await response.json();
  document.documentElement.lang = locale;
  try {
    localStorage.setItem(KEY, locale);
  } catch {
    /* private mode */
  }
  return locale;
}

export async function setLocale(lang) {
  return loadLocale(lang);
}
