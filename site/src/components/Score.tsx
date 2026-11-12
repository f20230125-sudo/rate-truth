"use client";

import { useState, useRef, useEffect } from "react";

export function Score({ value }: { value: number }) {
  const [shown, setShown] = useState(value);
  const previous = useRef(value);
  useEffect(() => {
    const from = previous.current;
    previous.current = value;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = reduce ? 1 : Math.min(1, (now - start) / 400);
      setShown(from + (value - from) * progress);
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return (
    <div className="score" aria-label={`${(value * 100).toFixed(1)} percent price accuracy`}>
      {(shown * 100).toFixed(1)}
      <span>%</span>
    </div>
  );
}
