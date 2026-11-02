/**
 * Thin fetch wrapper around the LakeWatch API.
 *
 * Every error response has the shape `{ error: { code, message, details } }`
 * (see backend `app/core/errors.py`), so failures are surfaced as a single
 * `ApiError` carrying the machine code and human message.
 */

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export interface ApiErrorShape {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: ApiErrorShape) {
    super(body.message || `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code || "error";
    this.details = body.details ?? {};
  }

  /** Field-level messages produced by request validation (422). */
  get fieldErrors(): Record<string, string> {
    const raw = this.details as { errors?: unknown };
    const out: Record<string, string> = {};
    if (Array.isArray(raw.errors)) {
      for (const item of raw.errors as Array<{ loc?: unknown[]; msg?: string }>) {
        const loc = Array.isArray(item.loc) ? item.loc : [];
        const field = loc.filter((p) => p !== "body" && p !== "query").join(".");
        if (field && item.msg) out[field] = item.msg;
      }
    }
    return out;
  }
}

const TOKEN_KEY = "lakewatch.token";

export function getStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode); the in-memory session still works */
  }
}

/** Called when the API rejects the current token so the app can sign out. */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  signal?: AbortSignal;
  /** Skip the Authorization header (used by login). */
  anonymous?: boolean;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${API_BASE_URL}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.append(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };

  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (!options.anonymous) {
    const token = getStoredToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, {
      code: "network_error",
      message: "Cannot reach the LakeWatch API. Is the backend running?",
      details: {},
    });
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload = text ? safeJson(text) : null;

  if (!response.ok) {
    if (response.status === 401) onUnauthorized?.();
    const body = extractError(payload, response.status);
    throw new ApiError(response.status, body);
  }

  return payload as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function extractError(payload: unknown, status: number): ApiErrorShape {
  if (payload && typeof payload === "object" && "error" in payload) {
    const error = (payload as { error?: Partial<ApiErrorShape> }).error;
    if (error && typeof error === "object") {
      return {
        code: error.code ?? "error",
        message: error.message ?? `Request failed with status ${status}`,
        details: (error.details as Record<string, unknown>) ?? {},
      };
    }
  }
  return {
    code: "error",
    message: `Request failed with status ${status}`,
    details: {},
  };
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"], signal?: AbortSignal) =>
    apiRequest<T>(path, { method: "GET", query, signal }),
  post: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: "POST", body }),
  put: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: "PUT", body }),
  patch: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: "PATCH", body }),
  del: <T>(path: string) => apiRequest<T>(path, { method: "DELETE" }),
};

/** Base URL for direct file links (exports) that the browser downloads. */
export function downloadUrl(path: string): string {
  const base = API_BASE_URL.replace(/\/$/, "");
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}
