import { useQuery } from "@tanstack/react-query";

const ALLOWED = new Set([
  "/api",
  "/api/teams",
  "/api/players",
  "/api/games",
  "/api/player-week-stats",
  "/api/load-runs",
]);

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export type Search = Record<string, string>;

export type Row = Record<string, unknown>;

export type ListBody = {
  data: Row[];
  page: { limit: number; offset: number; total: number };
};

export type DatasetRefresh = { dataset: string; finished_at: string };

export type ApiMeta = {
  last_refresh_et: string;
  datasets: DatasetRefresh[];
};

export function parityMessage(status: number): string {
  if (status === 503) return "The database is unavailable.";
  return "Something went wrong.";
}

function errorMessage(body: unknown): string | null {
  if (!body || typeof body !== "object" || !("error" in body)) return null;
  const error = (body as { error?: { message?: unknown } }).error;
  if (!error || typeof error.message !== "string" || error.message === "") return null;
  return error.message;
}

export async function getJson(path: string): Promise<unknown> {
  const split = path.indexOf("?");
  const pathname = split === -1 ? path : path.slice(0, split);
  const search = split === -1 ? "" : path.slice(split);
  if (!ALLOWED.has(pathname)) {
    throw new ApiError(0, "Something went wrong.");
  }
  let response: Response;
  try {
    response = await fetch(pathname + search);
  } catch {
    throw new ApiError(0, "Something went wrong.");
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const message = errorMessage(body);
    if (response.status >= 500 || response.status === 0) {
      throw new ApiError(response.status, parityMessage(response.status));
    }
    throw new ApiError(response.status, message ?? "Something went wrong.");
  }
  return body;
}

function isMeta(body: unknown): body is ApiMeta {
  if (!body || typeof body !== "object") return false;
  const record = body as { last_refresh_et?: unknown; datasets?: unknown };
  if (typeof record.last_refresh_et !== "string" || !Array.isArray(record.datasets)) return false;
  return record.datasets.every((item) => {
    if (!item || typeof item !== "object") return false;
    const row = item as { dataset?: unknown; finished_at?: unknown };
    return typeof row.dataset === "string" && typeof row.finished_at === "string";
  });
}

export async function getMeta(): Promise<ApiMeta> {
  const body = await getJson("/api");
  if (!isMeta(body)) {
    throw new ApiError(503, "The database is unavailable.");
  }
  return {
    last_refresh_et: body.last_refresh_et,
    datasets: body.datasets.map((item) => ({
      dataset: item.dataset,
      finished_at: item.finished_at,
    })),
  };
}

export function useApiMeta() {
  return useQuery({ queryKey: ["api"], queryFn: getMeta });
}

export function metaProblem(error: unknown, isError: boolean, isPending: boolean): string | null {
  if (isPending || !isError) return null;
  if (error instanceof ApiError) return error.message;
  return "Something went wrong.";
}

function isList(body: unknown): body is ListBody {
  if (!body || typeof body !== "object") return false;
  const record = body as { data?: unknown; page?: unknown };
  if (!Array.isArray(record.data) || !record.page || typeof record.page !== "object") return false;
  const page = record.page as { limit?: unknown; offset?: unknown; total?: unknown };
  return typeof page.limit === "number" && typeof page.offset === "number" && typeof page.total === "number";
}

export async function getList(path: string, search: Search): Promise<ListBody> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (value !== "") params.append(key, value);
  }
  const query = params.toString();
  const body = await getJson(query ? `${path}?${query}` : path);
  if (!isList(body)) throw new ApiError(0, "Something went wrong.");
  return {
    data: body.data,
    page: { limit: body.page.limit, offset: body.page.offset, total: body.page.total },
  };
}

export function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}
