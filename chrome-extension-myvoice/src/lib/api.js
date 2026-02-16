import { getBackendUrl } from "./config.js";

export class ApiError extends Error {
  constructor(message, status = 0, payload = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

function toMessage(status, payload, fallback = "Request failed") {
  if (payload && typeof payload === "object") {
    if (typeof payload.detail === "string" && payload.detail) return payload.detail;
    if (typeof payload.error === "string" && payload.error) return payload.error;
    if (typeof payload.message === "string" && payload.message) return payload.message;
  }
  return `${fallback} (HTTP ${status})`;
}

async function parsePayload(response) {
  const contentType = String(response.headers.get("content-type") || "").toLowerCase();
  if (contentType.includes("application/json")) {
    return response.json();
  }
  const text = await response.text();
  return text ? { message: text } : null;
}

async function request(path, init = {}) {
  const configuredBaseUrl = await getBackendUrl();
  const headers = { Accept: "application/json", ...(init.headers || {}) };
  const body = init.body;
  const isObjectBody = body && typeof body === "object" && !(body instanceof FormData);
  if (isObjectBody) headers["Content-Type"] = "application/json";

  const requestInit = {
    ...init,
    headers,
    body: isObjectBody ? JSON.stringify(body) : body,
    credentials: "include"
  };

  let response;
  try {
    response = await fetch(`${configuredBaseUrl}${path}`, requestInit);
  } catch (err) {
    const details = err instanceof Error ? err.message : String(err || "");
    throw new ApiError(
      `Network error. Can't reach backend at ${configuredBaseUrl}. Check Extension options.`,
      0,
      details ? { message: details } : null
    );
  }

  const payload = await parsePayload(response);

  if (!response.ok) {
    throw new ApiError(toMessage(response.status, payload), response.status, payload);
  }
  return payload;
}

export async function listPeople() {
  const all = [];
  const limit = 200;
  let offset = 0;
  while (true) {
    const batch = await request(`/people?limit=${limit}&offset=${offset}`, { method: "GET" });
    if (!Array.isArray(batch) || batch.length === 0) break;
    all.push(...batch);
    if (batch.length < limit) break;
    offset += limit;
  }
  return all;
}

export async function createPerson(payload) {
  return request("/people", {
    method: "POST",
    body: payload
  });
}

function toQuery(params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === "") continue;
    query.set(key, String(value));
  }
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export async function listPosts(params = {}) {
  return request(`/posts${toQuery(params)}`, { method: "GET" });
}

export async function createPost(payload) {
  return request("/posts", {
    method: "POST",
    body: payload
  });
}
