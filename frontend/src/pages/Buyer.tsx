import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, confirm, fmt, getPosition, getSale, joinQueue, money, naiveCheckout, Order, pay, reserve, Reservation, SaleInfo } from "../api";
import { usePoll } from "../usePoll";

type Step =
  | { name: "idle" }
  | { name: "waiting"; position: number; initial: number; length: number; wait: number }
  | { name: "admitted"; token: string }
  | { name: "reserved"; token: string; reservation: Reservation; key: string; note?: string }
  | { name: "paying"; reservation: Reservation; key: string }
  | { name: "done"; order: Order }
  | { name: "sold_out" }
  | { name: "expired" };

function useBuyerId() {
  const [id] = useState(() => {
    let existing = sessionStorage.getItem("rushline-buyer");
    if (!existing) {
      existing = `buyer-${Math.random().toString(36).slice(2, 8)}`;
      sessionStorage.setItem("rushline-buyer", existing);
    }
    return existing;
  });
  return id;
}

function useCountdown(expiresAt: number | null) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!expiresAt) return;
    const id = setInterval(() => setNow(Date.now() / 1000), 250);
    return () => clearInterval(id);
  }, [expiresAt]);
  return expiresAt ? Math.max(0, Math.ceil(expiresAt - now)) : 0;
}

// crypto.randomUUID only exists on https/localhost, so fall back for plain-http demos.
const newKey = () =>
  typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

export default function Buyer() {
  const buyerId = useBuyerId();
  const { data: sale } = usePoll(getSale, 3000);
  const [step, setStep] = useState<Step>({ name: "idle" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const stepRef = useRef(step);
  stepRef.current = step;

  const fail = (e: unknown) => {
    const err = e as ApiError;
    if (err.code === "sold_out") setStep({ name: "sold_out" });
    else if (err.code === "reservation_expired") setStep({ name: "expired" });
    else setError(err.message ?? "Something went wrong.");
  };

  // While waiting, poll our queue position every second.
  useEffect(() => {
    if (step.name !== "waiting") return;
    let alive = true;
    const id = setInterval(async () => {
      try {
        const s = await getPosition(buyerId);
        if (!alive) return;
        if (s.status === "admitted") setStep({ name: "admitted", token: s.token });
        else if (s.sold_out) setStep({ name: "sold_out" });
        else if (s.status === "waiting") setStep({ name: "waiting", position: s.position, initial: Math.max(stepRef.current.name === "waiting" ? (stepRef.current as { initial: number }).initial : 0, s.position), length: s.queue_length, wait: s.estimated_wait_seconds });
        else setStep({ name: "idle" });
      } catch (e) {
        // A 429 just means "slow down": keep waiting. Anything else is shown.
        if ((e as ApiError).status !== 429 && alive) fail(e);
      }
    }, 1000);
    return () => { alive = false; clearInterval(id); };
  }, [step.name, buyerId]);

  const run = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try { await fn(); } catch (e) { fail(e); }
    setBusy(false);
  }, []);

  const join = () => run(async () => {
    const s = await joinQueue(buyerId);
    if (s.status === "admitted") setStep({ name: "admitted", token: s.token });
    else if (s.status === "waiting") setStep({ name: "waiting", position: s.position, initial: s.position, length: s.queue_length, wait: s.estimated_wait_seconds });
    else if (s.sold_out) setStep({ name: "sold_out" });
  });

  const doReserve = (token: string) => run(async () => {
    const reservation = await reserve(buyerId, token);
    setStep({ name: "reserved", token, reservation, key: newKey() });
  });

  const doPay = (reservation: Reservation, key: string, token: string) => run(async () => {
    setStep({ name: "paying", reservation, key });
    try {
      await pay(reservation.reservation_id);
    } catch (e) {
      if ((e as ApiError).code === "payment_failed") {
        setStep({ name: "reserved", token, reservation, key, note: "Your payment didn't go through. Your item is still held, so try again." });
        return;
      }
      throw e;
    }
    // The same Idempotency-Key is reused on every retry, so a double-submit can never double-order.
    const order = await confirm(reservation.reservation_id, key);
    setStep({ name: "done", order });
  });

  const naiveBuy = () => run(async () => {
    const r = await naiveCheckout(buyerId);
    setStep({ name: "done", order: { order_id: r.order_id, buyer_id: buyerId, amount_cents: sale?.price_cents ?? 0, replayed: false } });
  });

  const reset = () => { setStep({ name: "idle" }); setError(null); };

  const stepIndex = { idle: 0, waiting: 0, admitted: 1, reserved: 1, paying: 2, done: 3, sold_out: 0, expired: 0 }[step.name];

  return (
    <div className="buyer-page">
      <div className="buyer-card">
        <ProductHeader sale={sale ?? null} />
        {sale?.mode === "safe" && <Stepper active={stepIndex} finished={step.name === "done"} />}
        <div className="buyer-step">
          {!sale && <p className="muted center">Loading the drop...</p>}
          {sale && sale.mode === "naive" && <NaivePanel step={step} sale={sale} busy={busy} onBuy={naiveBuy} onReset={reset} />}
          {sale && sale.mode === "safe" && (
            <SafePanel step={step} sale={sale} busy={busy} onJoin={join} onReserve={doReserve} onPay={doPay}
              onReset={reset} onExpire={() => setStep({ name: "expired" })} />
          )}
          {error && <p className="error-text center">{error}</p>}
        </div>
        <div className="buyer-foot muted small">You are {buyerId}</div>
      </div>
    </div>
  );
}

function ProductHeader({ sale }: { sale: SaleInfo | null }) {
  return (
    <div className="product-head">
      <div className="product-art" aria-hidden="true">
        <svg viewBox="0 0 120 120" width="56" height="56">
          <path d="M40 24 60 34 80 24 104 40 92 62 82 56V100H38V56L28 62 16 40Z" fill="#7C5CFC" />
          <path d="M44 68 76 68M44 80 76 80" stroke="#fff" strokeWidth="5" strokeLinecap="round" />
        </svg>
      </div>
      <div className="product-meta">
        <div className="product-name">{sale?.name ?? "Loading"}</div>
        <div className="product-price">{sale ? money(sale.price_cents) : ""}</div>
      </div>
      {sale && (
        <span className={`chip ${sale.stock_left === 0 ? "chip-bad" : sale.stock_left <= 10 ? "chip-warn" : "chip-neutral"}`}>
          {sale.stock_left === 0 ? "Sold out" : `${fmt(sale.stock_left)} of ${fmt(sale.initial_stock)} left`}
        </span>
      )}
    </div>
  );
}

const STEPS = ["Queue", "Reserve", "Pay", "Done"];

function Stepper({ active, finished }: { active: number; finished: boolean }) {
  return (
    <ol className="stepper" aria-label="Checkout progress">
      {STEPS.map((label, i) => (
        <li key={label} className={i < active || finished ? "done" : i === active ? "current" : ""}>
          <span className="step-dot">{i < active || finished ? "\u2713" : i + 1}</span>
          <span className="step-label">{label}</span>
        </li>
      ))}
    </ol>
  );
}

/** Circular countdown ring with the time left in the middle. */
function Timer({ left, total }: { left: number; total: number }) {
  const r = 52, c = 2 * Math.PI * r;
  const urgent = left <= 20;
  return (
    <div className={`timer ${urgent ? "urgent" : ""}`} role="timer" aria-label={`${mmss(left)} left`}>
      <svg viewBox="0 0 120 120" width="148" height="148">
        <circle cx="60" cy="60" r={r} className="timer-track" />
        <circle cx="60" cy="60" r={r} className="timer-arc" strokeDasharray={c}
          strokeDashoffset={c * (1 - Math.min(1, left / Math.max(total, 1)))} transform="rotate(-90 60 60)" />
      </svg>
      <div className="timer-text"><b>{mmss(left)}</b><span>left to pay</span></div>
    </div>
  );
}

function SafePanel({ step, sale, busy, onJoin, onReserve, onPay, onReset, onExpire }: {
  step: Step; sale: SaleInfo; busy: boolean; onExpire: () => void;
  onJoin: () => void; onReserve: (token: string) => void;
  onPay: (r: Reservation, key: string, token: string) => void; onReset: () => void;
}) {
  const expiresAt = step.name === "reserved" || step.name === "paying" ? step.reservation.expires_at : null;
  const left = useCountdown(expiresAt);

  // If the countdown hits zero while holding a reservation, show the friendly expired state.
  useEffect(() => {
    if (step.name === "reserved" && left === 0) onExpire();
  }, [left, step.name, onExpire]);

  switch (step.name) {
    case "idle":
      if (sale.stock_left === 0) return <Message title="Sold out" body="This drop is gone. Thanks for being here, the next one is coming soon." />;
      return (
        <div className="center">
          <h2>Join the waiting room</h2>
          <p className="muted">Everyone lines up fairly. When it's your turn you get {Math.round(sale.reservation_ttl_seconds / 60)} minutes to check out.</p>
          <button className="btn primary wide" disabled={busy} onClick={onJoin}>Join the queue</button>
        </div>
      );
    case "waiting": {
      const done = step.initial > 1 ? Math.round(((step.initial - step.position) / (step.initial - 1)) * 100) : 100;
      return (
        <div className="center">
          <span className="chip chip-warn">In the waiting room</span>
          <div className="big-number">#{fmt(step.position)}</div>
          <p className="muted">of {fmt(step.length)} waiting · about {Math.max(1, Math.round(step.wait))}s to go</p>
          <div className="progress" role="progressbar" aria-valuenow={done} aria-valuemin={0} aria-valuemax={100}><div style={{ width: `${Math.max(done, 4)}%` }} /></div>
          <p className="muted small">Keep this tab open. We'll let you in automatically.</p>
        </div>
      );
    }
    case "admitted":
      return (
        <div className="center">
          <span className="chip chip-good">You're in</span>
          <h2>It's your turn</h2>
          <p className="muted">Reserve your item to hold it for {Math.round(sale.reservation_ttl_seconds / 60)} minutes while you pay.</p>
          <button className="btn primary wide" disabled={busy} onClick={() => onReserve(step.token)}>Reserve now</button>
        </div>
      );
    case "reserved":
    case "paying": {
      const r = step.reservation;
      const token = step.name === "reserved" ? step.token : "";
      return (
        <div className="center">
          <Timer left={left} total={sale.reservation_ttl_seconds} />
          {step.name === "reserved" && step.note && <p className="error-text">{step.note}</p>}
          <button className="btn primary wide" disabled={busy || step.name === "paying"} onClick={() => onPay(r, step.key, token)}>
            {step.name === "paying" ? "Processing payment..." : `Pay ${money(r.amount_cents)}`}
          </button>
        </div>
      );
    }
    case "done":
      return (
        <div className="center">
          <div className="check">{"\u2713"}</div>
          <h2>You got it</h2>
          <p className="muted">Order confirmed for {money(step.order.amount_cents)}.</p>
          <span className="chip chip-neutral mono">Order {step.order.order_id.slice(0, 8)}</span>
        </div>
      );
    case "sold_out":
      return <Message title="Sold out" body="Every unit is taken. Thanks for waiting, the next drop is coming soon." action={<button className="btn secondary" onClick={onReset}>Back</button>} />;
    case "expired":
      return <Message title="Your reservation expired" body="No worries, your item went back into stock. If any is left you can try again." warn action={<button className="btn primary" onClick={onReset}>Try again</button>} />;
  }
}

function NaivePanel({ step, sale, busy, onBuy, onReset }: { step: Step; sale: SaleInfo; busy: boolean; onBuy: () => void; onReset: () => void }) {
  if (step.name === "done")
    return <div className="center"><div className="check">{"\u2713"}</div><h2>Order placed</h2><span className="chip chip-neutral mono">Order {step.order.order_id.slice(0, 8)}</span></div>;
  if (step.name === "sold_out" || sale.stock_left === 0)
    return <Message title="Sold out" body="This drop is gone." action={step.name === "sold_out" ? <button className="btn secondary" onClick={onReset}>Back</button> : undefined} />;
  return (
    <div className="center">
      <span className="chip chip-warn">Naive mode</span>
      <h2>Direct checkout</h2>
      <p className="muted">No waiting room and no reservation. This is the unsafe path kept for comparison. Switch to Safe on the dashboard for the full flow.</p>
      <button className="btn primary wide" disabled={busy} onClick={onBuy}>Buy now</button>
    </div>
  );
}

function Message({ title, body, warn, action }: { title: string; body: string; warn?: boolean; action?: React.ReactNode }) {
  return (
    <div className="center">
      <span className={`chip ${warn ? "chip-warn" : "chip-neutral"}`}>{warn ? "Expired" : "Closed"}</span>
      <h2>{title}</h2>
      <p className="muted">{body}</p>
      {action}
    </div>
  );
}
