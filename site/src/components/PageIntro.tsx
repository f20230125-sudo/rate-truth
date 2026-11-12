"use client";

import { type ReactNode } from "react";

export function PageIntro({
  number,
  title,
  children,
}: {
  number: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="intro">
      <p className="eyebrow">RATE TRUTH / {number}</p>
      <h1>{title}</h1>
      <p className="lede">{children}</p>
    </div>
  );
}
