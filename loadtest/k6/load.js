// Rushline load test. One script, three scenarios, two modes:
//   k6 run -e SCENARIO=spike -e MODE=safe loadtest/k6/load.js
//
// SCENARIO: steady | spike | abandon        MODE: naive | safe
// The orchestrator (loadtest/run-comparison.mjs) creates the sale before each run.
import http from "k6/http";
import { sleep } from "k6";
import exec from "k6/execution";
import { Counter, Trend } from "k6/metrics";

const BASE = __ENV.BASE_URL || "http://localhost:8000";
const MODE = __ENV.MODE || "safe";
const SCENARIO = __ENV.SCENARIO || "spike";

// 4xx are normal business answers (sold out, payment failed, rate limited). Only 5xx and
// network failures count as errors in http_req_failed.
http.setResponseCallback(http.expectedStatuses({ min: 200, max: 499 }));

// Latency of every request EXCEPT /pay, whose delay is the fake payment provider sleeping on purpose.
const latAll = new Trend("lat_all", true);
// Latency of the contended step: naive checkout, or safe-mode reserve.
const latBuy = new Trend("lat_buy", true);
const purchases = new Counter("purchases");      // buyers who finished with an order
const soldOut = new Counter("sold_out");         // buyers told "sold out"
const abandoned = new Counter("abandoned");      // buyers who walked away
const rateLimited = new Counter("rate_limited"); // 429 responses

// Each scenario describes how buyers arrive and what they do.
const SCENARIOS = {
  // Normal busy day: 100 new buyers per second for 30 seconds, plenty of stock.
  steady: {
    executor: "constant-arrival-rate", rate: 100, timeUnit: "1s", duration: "30s",
    preAllocatedVUs: 400, maxVUs: 2000, abandonRate: 0,
  },
  // Black Friday: 5,000 buyers hit "buy" at the same moment for 100 units.
  spike: {
    executor: "shared-iterations", vus: 5000, iterations: 5000, maxDuration: "180s", abandonRate: 0,
  },
  // 10 new buyers per second for 60s; 70% reserve an item and never pay.
  abandon: {
    executor: "constant-arrival-rate", rate: 10, timeUnit: "1s", duration: "60s",
    preAllocatedVUs: 200, maxVUs: 1000, abandonRate: 0.7,
  },
};
const cfg = SCENARIOS[SCENARIO];
const { abandonRate, ...executorOptions } = cfg;

export const options = {
  scenarios: { buyers: { ...executorOptions, exec: "buyer" } },
  summaryTrendStats: ["avg", "min", "med", "max", "p(90)", "p(95)", "p(99)"],
  discardResponseBodies: false,
};

function call(name, method, path, body, headers = {}) {
  const res = http.request(method, `${BASE}${path}`, body ? JSON.stringify(body) : null, {
    headers: { "Content-Type": "application/json", ...headers },
    tags: { name },
  });
  if (name !== "pay") latAll.add(res.timings.duration);
  if (res.status === 429) rateLimited.add(1);
  return res;
}

const json = (res) => {
  try { return res.json(); } catch (e) { return {}; }
};

export function buyer() {
  const id = `k6-${SCENARIO}-${exec.scenario.iterationInTest}`;
  if (MODE === "naive") naiveJourney(id);
  else safeJourney(id);
}

function naiveJourney(id) {
  if (Math.random() < abandonRate) { abandoned.add(1); return; }  // never even tries to buy
  const res = call("checkout", "POST", "/naive/checkout", { buyer_id: id });
  latBuy.add(res.timings.duration);
  if (res.status === 201) purchases.add(1);
  else if (res.status === 409) soldOut.add(1);
}

function safeJourney(id) {
  // 1. Waiting room
  call("join", "POST", "/queue/join", { buyer_id: id });
  let token = null;
  for (let poll = 0; poll < 120 && !token; poll++) {
    sleep(1 + Math.random() * 0.5);
    const res = call("position", "GET", `/queue/position?buyer_id=${id}`);
    if (res.status !== 200) continue;
    const body = json(res);
    if (body.status === "admitted") token = body.token;
    else if (body.sold_out) { soldOut.add(1); return; }
  }
  if (!token) return;

  // 2. Reserve (the contended step)
  const reserve = call("reserve", "POST", "/reserve", { buyer_id: id }, { "X-Admission-Token": token });
  latBuy.add(reserve.timings.duration);
  if (reserve.status === 409) { soldOut.add(1); return; }
  if (reserve.status !== 201) return;
  const reservationId = json(reserve).reservation_id;

  if (Math.random() < abandonRate) { abandoned.add(1); return; }  // walks away holding the item

  // 3. Pay (fake provider, retry failures a few times)
  let paid = false;
  for (let attempt = 0; attempt < 5 && !paid; attempt++) {
    const res = call("pay", "POST", "/pay", { reservation_id: reservationId });
    if (res.status === 200) paid = true;
    else if (res.status !== 402) return;
  }
  if (!paid) return;

  // 4. Confirm
  const confirm = call("confirm", "POST", "/confirm", { reservation_id: reservationId },
    { "Idempotency-Key": `${id}-confirm` });
  if (confirm.status === 201) purchases.add(1);
}
