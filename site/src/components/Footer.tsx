"use client";

import Link from "next/link";

export function Footer() {
  return (
    <footer className="footer wrap">
      <p>
        Synthetic rates. Real hotels from OpenStreetMap.
        <br />
        Built to Google’s published formats.
      </p>
      <p>
        <Link href="/method">Method, limits & connect ↗</Link>
        <br />
        <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors, ODbL</a>
      </p>
    </footer>
  );
}
