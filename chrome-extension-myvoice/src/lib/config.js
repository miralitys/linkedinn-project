export const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
const BACKEND_URL_KEY = "myvoice_backend_url";
export const PENDING_URL_KEY = "myvoice_pending_linkedin_url";
export const PENDING_TAB_ID_KEY = "myvoice_pending_linkedin_tab_id";

export function normalizeBackendUrl(input) {
  const raw = String(input || "").trim();
  if (!raw) return DEFAULT_BACKEND_URL;
  const withScheme = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
  let normalized = withScheme.replace(/\/+$/, "");
  try {
    const parsed = new URL(normalized);
    const host = parsed.hostname.toLowerCase();
    const isLocalHost = host === "localhost" || host === "127.0.0.1" || host === "127.0.0.2";
    if (isLocalHost && parsed.protocol === "https:") {
      parsed.protocol = "http:";
      normalized = parsed.toString().replace(/\/+$/, "");
    }
  } catch {
    // Keep best-effort normalized value for malformed URLs.
  }
  return normalized;
}

export async function getBackendUrl() {
  const data = await chrome.storage.sync.get(BACKEND_URL_KEY);
  return normalizeBackendUrl(data[BACKEND_URL_KEY] || DEFAULT_BACKEND_URL);
}

export async function setBackendUrl(url) {
  const normalized = normalizeBackendUrl(url);
  await chrome.storage.sync.set({ [BACKEND_URL_KEY]: normalized });
  return normalized;
}
