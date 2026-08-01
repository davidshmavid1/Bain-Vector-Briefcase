import type { BriefRequest, CompanyBrief } from "./types";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** FastAPI returns `detail` as a string, or as a list of validation errors. */
function readDetail(payload: unknown): string | null {
  if (typeof payload !== "object" || payload === null) return null;
  const detail = (payload as { detail?: unknown }).detail;

  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) =>
        typeof entry === "object" && entry !== null && typeof (entry as { msg?: unknown }).msg === "string"
          ? ((entry as { msg: string }).msg.replace(/^Value error,\s*/, ""))
          : null,
      )
      .filter((message): message is string => Boolean(message));
    if (messages.length > 0) return messages.join(" ");
  }
  return null;
}

export async function generateBrief(
  request: BriefRequest,
  signal?: AbortSignal,
): Promise<CompanyBrief> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/v1/brief`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(
      "Could not reach the brief service. Check that the API is running and try again.",
      0,
    );
  }

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    throw new ApiError(
      readDetail(payload) ?? "The brief could not be generated. Please try again.",
      response.status,
    );
  }
  if (payload === null) {
    throw new ApiError("The brief service returned an unreadable response.", response.status);
  }
  return payload as CompanyBrief;
}
