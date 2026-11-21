// Central API configuration.
// Desktop app: Electron's preload provides the backend address at runtime (its port is chosen at startup).
// Web/Docker: set VITE_API_BASE_URL in frontend/.env (baked in at build time).
const desktopBase = typeof window !== 'undefined' && window.pkos && window.pkos.apiBase;
const BASE = desktopBase || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
export const API_BASE = BASE;
export const API = `${BASE}/api/v1`;
export const IS_DESKTOP = Boolean(desktopBase);
