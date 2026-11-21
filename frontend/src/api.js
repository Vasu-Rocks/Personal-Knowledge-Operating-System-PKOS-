// Central API configuration.
// Set VITE_API_BASE_URL in frontend/.env to override (e.g., for staging).
const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
export const API_BASE = BASE;
export const API = `${BASE}/api/v1`;
