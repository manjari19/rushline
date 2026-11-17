// Thin typed client for the Rushline backend. All calls go through /api (proxied).

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public retryAfter?: number) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "network", "Can't reach the server. Check your connection.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    const code = typeof d === "object" && d?.code ? d.code : "error";
    const message = typeof d === "object" && d?.message ? d.message : "Something went wrong.";
    throw new ApiError(res.status, code, message, Number(res.headers.get("Retry-After")) || undefined);
  }
  return data as T;
}

const post = <T>(path: string, body: unknown, headers: Record<string, string> = {}) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body), headers });

// ---- types ----------------------------------------------------------------

export type Mode = "naive" | "safe";

export interface SeriesPoint { t: number; rps: number; avg_ms: number }
export interface RushStatus { total: number; finished: number; running: boolean; bought: number; sold_out: number; abandoned: number; errors: number }
export interface Stats {
  sale_id: number; name: string; mode: Mode; initial_stock: number;
  stock_left: number; queue_length: number; active_reservations: number;
  confirmed_orders: number; oversold_units: number; rps: number; avg_latency_ms: number;
  rush: RushStatus; series: SeriesPoint[];
}
export interface SaleInfo {
  sale_id: number; name: string; price_cents: number; mode: Mode;
  stock_left: number; initial_stock: number; reservation_ttl_seconds: number;
}
export type QueueStatus =
  | { status: "waiting"; position: number; queue_length: number; estimated_wait_seconds: number; sold_out: boolean }
  | { status: "admitted"; token: string; expires_in: number; sold_out: boolean }
  | { status: "not_in_queue"; sold_out: boolean };
export interface Reservation { reservation_id: string; expires_at: number; amount_cents: number; resumed: boolean }
export type EventType = "waiting" | "reserved" | "confirmed" | "expired" | "rejected";
export interface ActivityEvent { buyer_id: string; event: EventType; units: number; ts: number }
export interface Order { order_id: string; buyer_id: string; amount_cents: number; replayed: boolean }

// ---- admin ----------------------------------------------------------------

export const getStats = () => request<Stats>("/admin/stats");
export const getEvents = (limit = 12) =>
  request<{ events: ActivityEvent[] }>(`/admin/events?limit=${limit}`).then((r) => r.events);
export const createSale = (stock: number, mode: Mode) => post("/admin/sale", { stock, mode });
export const startRush = (buyers: number) => post("/admin/rush", { buyers });

// ---- buyer ----------------------------------------------------------------

export const getSale = () => request<SaleInfo>("/sale");
export const joinQueue = (buyer_id: string) => post<QueueStatus>("/queue/join", { buyer_id });
export const getPosition = (buyer_id: string) =>
  request<QueueStatus>(`/queue/position?buyer_id=${encodeURIComponent(buyer_id)}`);
export const reserve = (buyer_id: string, token: string) =>
  post<Reservation>("/reserve", { buyer_id }, { "X-Admission-Token": token });
export const pay = (reservation_id: string) => post<{ status: string }>("/pay", { reservation_id });
export const confirm = (reservation_id: string, key: string) =>
  post<Order>("/confirm", { reservation_id }, { "Idempotency-Key": key });
export const naiveCheckout = (buyer_id: string) => post<{ order_id: string }>("/naive/checkout", { buyer_id });

export const money = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);

/** Thousands separators everywhere (1,900 not 1900). */
export const fmt = (n: number) => n.toLocaleString("en-US");
