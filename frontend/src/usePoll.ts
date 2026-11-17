import { useEffect, useRef, useState } from "react";

/** Calls `fn` now and then every `ms`; returns the latest result (or error). */
export function usePoll<T>(fn: () => Promise<T>, ms: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const result = await fnRef.current();
        if (alive) { setData(result); setError(null); }
      } catch (e) {
        if (alive) setError(e as Error);
      }
    };
    tick();
    const id = setInterval(tick, ms);
    return () => { alive = false; clearInterval(id); };
  }, [ms]);

  return { data, error };
}
