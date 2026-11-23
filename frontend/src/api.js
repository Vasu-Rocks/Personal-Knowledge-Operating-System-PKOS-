// Central API configuration.
// Desktop app: Electron's preload provides the backend address at runtime (its port is chosen at startup).
// Web/Docker: set VITE_API_BASE_URL in frontend/.env (baked in at build time).
// Phone access: the laptop's phone server serves this page and marks it, so the API is on the same address.
const desktopBase = typeof window !== 'undefined' && window.pkos && window.pkos.apiBase;
const servedToPhone = typeof document !== 'undefined'
  && document.querySelector('meta[name="pkos-api"][content="same-origin"]') !== null;
const BASE = desktopBase || (servedToPhone ? window.location.origin : null)
  || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
export const API_BASE = BASE;
export const API = `${BASE}/api/v1`;
export const IS_DESKTOP = Boolean(desktopBase);
export const IS_PHONE_ACCESS = Boolean(!desktopBase && servedToPhone);
