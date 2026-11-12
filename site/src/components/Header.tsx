"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { ThemeToggle } from "./ThemeToggle";

export function Header() {
  const path = usePathname();
  return (
    <header className="header wrap">
      <Link className="brand" href="/">
        Rate Truth<span className="label">DUBAI / SUPPLIER → AGENT → FEED</span>
      </Link>
      <ThemeToggle />
      <nav aria-label="Main">
        {[
          ["/", "Desk"],
          ["/hotels", "Hotels"],
          ["/accuracy", "Accuracy"],
          ["/feeds", "Feeds"],
          ["/taxes", "Taxes"],
          ["/method", "Method / Connect"],
        ].map(([href, label]) => (
          <Link key={href} href={href} aria-current={path === href ? "page" : undefined}>
            {href === "/method" ? (
              <>
                <span className="nav-desktop">{label}</span>
                <span className="nav-phone">Method</span>
              </>
            ) : (
              label
            )}
          </Link>
        ))}
      </nav>
    </header>
  );
}
