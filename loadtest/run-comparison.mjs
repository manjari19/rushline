#!/usr/bin/env node
// Runs every scenario against naive and safe mode, and saves the results.
//
//   node loadtest/run-comparison.mjs                       full comparison (about 10 minutes)
//   SCENARIOS=spike MODES=safe node loadtest/run-comparison.mjs   just one cell
//
// Needs: Docker (stack is started for you), k6, Node 18+. No npm install required.
import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = path.join(ROOT, "loadtest", "results");
const BASE = "http://localhost:8000";

// Benchmark settings. Admission is raised so the test measures the checkout engine, not the
// waiting room's deliberate 50/s throttle. The activity feed is off to save a Redis write per request.
const BENCH_ENV = { ADMISSION_RATE_PER_SECOND: "1000", ACTIVITY_LOG: "false" };
const SCENARIOS = {
  steady: { stock: 10000, env: {}, blurb: "100 new buyers/s for 30 s, stock 10,000" },
  spike: { stock: 100, env: {}, blurb: "5,000 buyers at once, stock 100" },
  abandon: { stock: 100, env: { RESERVATION_TTL_SECONDS: "10" }, blurb: "10 buyers/s for 60 s, 70% abandon, stock 100, 10 s reservation TTL" },
};
const pick = (name, all) => (process.env[name] ? process.env[name].split(",") : all);
const scenarios = pick("SCENARIOS", Object.keys(SCENARIOS));
const modes = pick("MODES", ["naive", "safe"]);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (...a) => console.log(new Date().toLocaleTimeString(), ...a);

function sh(cmd, args, opts = {}) {
  return spawnSync(cmd, args, { cwd: ROOT, encoding: "utf8", ...opts });
}

function recreateBackend(extraEnv) {
  const r = sh("docker", ["compose", "up", "-d", "--force-recreate", "--no-deps", "api", "worker"], {
    env: { ...process.env, ...extraEnv },
  });
  if (r.status !== 0) throw new Error(`docker compose failed: ${r.stderr}`);
}

async function waitForHealth() {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(`${BASE}/health`)).ok) return; } catch {}
    await sleep(1000);
  }
  throw new Error("API did not become healthy");
}

const api = async (p, body) => {
  const res = await fetch(`${BASE}${p}`, body
    ? { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }
    : undefined);
  return res.json();
};

/** Wait until queued/reserved buyers have drained (reservations expire, queue empties). */
async function settle() {
  for (let i = 0; i < 60; i++) {
    const s = await api("/admin/stats");
    if (s.active_reservations === 0 && s.queue_length === 0) return s;
    await sleep(1000);
  }
  return api("/admin/stats");
}

function runK6(scenario, mode, summaryFile) {
  // 5,000 virtual buyers need thousands of sockets, so raise the open-file limit first.
  const cmd = `ulimit -n 65535 2>/dev/null; exec k6 run --quiet --summary-export="${summaryFile}" ` +
    `-e SCENARIO=${scenario} -e MODE=${mode} -e BASE_URL=${BASE} loadtest/k6/load.js`;
  return sh("sh", ["-c", cmd], { stdio: ["ignore", "inherit", "inherit"], encoding: undefined });
}

// k6 summary files have changed shape between versions, so read values defensively.
const val = (metric, key) => metric?.values?.[key] ?? metric?.[key] ?? null;
const round = (n, d = 1) => (n == null ? null : Math.round(n * 10 ** d) / 10 ** d);

function summarize(scenario, mode, stats, summary, reconcile, wallSeconds) {
  const m = summary.metrics;
  const failed = val(m.http_req_failed, "rate") ?? val(m.http_req_failed, "value");
  return {
    scenario, mode,
    description: SCENARIOS[scenario].blurb,
    stock: stats.initial_stock,
    duration_s: round(wallSeconds),
    http_requests: val(m.http_reqs, "count"),
    throughput_rps: round(val(m.http_reqs, "rate")),
    buyers_per_s: round(val(m.iterations, "rate")),
    buyers: val(m.iterations, "count"),
    latency_ms: { p50: round(val(m.lat_all, "med")), p95: round(val(m.lat_all, "p(95)")), p99: round(val(m.lat_all, "p(99)")) },
    buy_latency_ms: { p50: round(val(m.lat_buy, "med")), p95: round(val(m.lat_buy, "p(95)")), p99: round(val(m.lat_buy, "p(99)")) },
    error_rate_pct: round(failed * 100, 2),
    rate_limited: val(m.rate_limited, "count") ?? 0,
    buyers_purchased: val(m.purchases, "count") ?? 0,
    buyers_sold_out: val(m.sold_out, "count") ?? 0,
    buyers_abandoned: val(m.abandoned, "count") ?? 0,
    confirmed_orders: stats.confirmed_orders,
    oversold_units: stats.oversold_units,
    stock_left: stats.stock_left,
    reconcile_ok: reconcile.ok,
    reconcile_output: reconcile.output,
  };
}

const fmt = (n) => (n == null ? "n/a" : n.toLocaleString("en-US"));

function markdown(results, meta) {
  const lines = [
    `Measured on ${meta.cpu}, ${meta.cores} cores, ${meta.memory_gb} GB RAM, ${meta.platform}; API, worker, Postgres and Redis in Docker Desktop; k6 on the same machine.`,
    `Run on ${meta.date}. Waiting room admission raised to 1,000/s for these runs; latency excludes \`/pay\` (the fake provider sleeps on purpose).`,
    "",
    "| Scenario | Mode | Buyers | Throughput (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | Orders | Oversold |",
    "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
  ];
  for (const r of results) {
    lines.push(`| ${r.scenario} | ${r.mode} | ${fmt(r.buyers)} | ${fmt(r.throughput_rps)} | ${r.latency_ms.p50} | ${r.latency_ms.p95} | ${r.latency_ms.p99} | ${r.error_rate_pct}% | ${fmt(r.confirmed_orders)} / ${fmt(r.stock)} | ${fmt(r.oversold_units)} |`);
  }
  lines.push("", "Latency of the contended step only (naive checkout, or safe-mode reserve):", "",
    "| Scenario | Mode | p50 (ms) | p95 (ms) | p99 (ms) |", "|---|---|---:|---:|---:|");
  for (const r of results) lines.push(`| ${r.scenario} | ${r.mode} | ${r.buy_latency_ms.p50} | ${r.buy_latency_ms.p95} | ${r.buy_latency_ms.p99} |`);
  return lines.join("\n") + "\n";
}

async function main() {
  mkdirSync(path.join(OUT, "raw"), { recursive: true });
  const t0 = Date.now();
  log("starting stack...");
  const up = sh("docker", ["compose", "up", "-d", "--build"], { env: { ...process.env, ...BENCH_ENV } });
  if (up.status !== 0) throw new Error(up.stderr);

  const results = [];
  for (const scenario of scenarios) {
    for (const mode of modes) {
      log(`=== ${scenario} / ${mode}: ${SCENARIOS[scenario].blurb}`);
      recreateBackend({ ...BENCH_ENV, ...SCENARIOS[scenario].env });
      await waitForHealth();
      await sleep(2000);
      await api("/admin/sale", { stock: SCENARIOS[scenario].stock, mode, price_cents: 4900 });

      const summaryFile = path.join(OUT, "raw", `${scenario}-${mode}.json`);
      const started = Date.now();
      const k6 = runK6(scenario, mode, summaryFile);
      const wall = (Date.now() - started) / 1000;
      if (k6.status !== 0) log(`k6 exited with status ${k6.status} (continuing; results may be partial)`);

      log("settling...");
      const stats = await settle();
      const rec = sh("docker", ["compose", "exec", "-T", "api", "python", "-m", "app.reconcile"]);
      const reconcile = { ok: rec.status === 0, output: (rec.stdout || "").trim() };

      const row = summarize(scenario, mode, stats, JSON.parse(readFileSync(summaryFile, "utf8")), reconcile, wall);
      results.push(row);
      log(`    ${row.throughput_rps} req/s, p95 ${row.latency_ms.p95} ms, errors ${row.error_rate_pct}%, orders ${row.confirmed_orders}/${row.stock}, oversold ${row.oversold_units}`);
    }
  }

  // Put the stack back to its normal settings.
  recreateBackend({});

  const meta = {
    date: new Date().toISOString().slice(0, 10),
    cpu: os.cpus()[0].model, cores: os.cpus().length,
    memory_gb: Math.round(os.totalmem() / 2 ** 30), platform: `${os.type()} ${os.release()}`,
    bench_env: BENCH_ENV, total_minutes: round((Date.now() - t0) / 60000),
  };
  // A filtered run must never overwrite the full comparison.
  const name = process.env.SCENARIOS || process.env.MODES ? "results-partial" : "results";
  writeFileSync(path.join(OUT, `${name}.json`), JSON.stringify({ meta, results }, null, 2));
  writeFileSync(path.join(OUT, `${name}.md`), markdown(results, meta));
  log(`saved loadtest/results/${name}.json and ${name}.md (${meta.total_minutes} min)`);
}

main().catch((e) => { console.error(e); process.exit(1); });
