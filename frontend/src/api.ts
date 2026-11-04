import type { Diagnostic } from "./types";
export class ApiError extends Error {
  diagnostics: Diagnostic[];
  constructor(message: string, diagnostics: Diagnostic[] = []) {
    super(message);
    this.diagnostics = diagnostics;
  }
}
export async function api<T>(
  path: string,
  body?: unknown,
  method = body === undefined ? "GET" : "POST",
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw new ApiError(
      data.error?.message || "The local request failed.",
      data.error?.diagnostics || [],
    );
  return data as T;
}
export const download = (run: string, name: string) =>
  `/api/v1/runs/${encodeURIComponent(run)}/artifacts/${name}`;
