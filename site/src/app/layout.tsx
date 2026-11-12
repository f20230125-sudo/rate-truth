import "@fontsource-variable/schibsted-grotesk";
import "@fontsource-variable/public-sans";
import "@fontsource-variable/martian-mono";
import "./globals.css";
import type { Metadata } from "next";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { Keyboard } from "@/components/Keyboard";
export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3170"),
  title: { default: "Rate Truth · Every price has a paper trail", template: "%s · Rate Truth" },
  description:
    "A Dubai hotel supplier desk. Synthetic rates on real hotels, itemised folios, streamed MCP tools and price accuracy audits. Built to Google’s published formats.",
  openGraph: {
    title: "Rate Truth · Every price has a paper trail",
    description: "Real hotels. Synthetic rates. Every amount traced to a supplier folio.",
    type: "website",
    locale: "en_AE",
    siteName: "Rate Truth",
  },
  twitter: {
    card: "summary",
    title: "Rate Truth",
    description: "Every price has a paper trail. A Dubai hotel supplier desk.",
  },
};
const script = `try{var t=localStorage.getItem('rt-theme');document.documentElement.dataset.theme=t==='dark'?'dark':'light'}catch(e){document.documentElement.dataset.theme='light'}`;
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: script }} />
      </head>
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        <Header />
        <Keyboard />
        <main className="wrap" id="main">
          {children}
        </main>
        <Footer />
      </body>
    </html>
  );
}
