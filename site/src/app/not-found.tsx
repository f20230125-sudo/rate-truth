import Link from "next/link";
export default function NotFound() {
  return (
    <div className="intro">
      <p className="eyebrow">404 / NO ENTRY</p>
      <h1>This page is not in the ledger.</h1>
      <p>
        <Link href="/">Return to the desk ↗</Link>
      </p>
    </div>
  );
}
