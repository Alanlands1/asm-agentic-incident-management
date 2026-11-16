"use client";

import { useEffect, useRef, useState } from "react";

/** A number that counts up to its value when it appears or changes; it is set at once when the viewer asked for less motion. */
export function CountUp({ value }: { value: number }) {
  const [shown, setShown] = useState(0);
  const last = useRef(0);
  useEffect(() => {
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const from = last.current;
    const start = performance.now();
    let frame = requestAnimationFrame(function tick(now) {
      const done = still ? 1 : Math.min((now - start) / 600, 1);
      last.current = Math.round(from + (value - from) * (1 - (1 - done) ** 3));
      setShown(last.current);
      if (done < 1) frame = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return (
    <>
      <span aria-hidden="true">{shown}</span>
      <span className="sr-only">{value}</span>
    </>
  );
}
