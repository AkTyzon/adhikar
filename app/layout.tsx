import type { Metadata, Viewport } from "next";

import { HELPLINES } from "@/lib/legal-db";
import "./globals.css";

export const metadata: Metadata = {
  title: "Adhikar — Know your rights | AI legal help for India",
  description:
    "Understand Indian law in plain language, in your own language. Adhikar cites the exact section of the BNS, BNSS, PWDVA, Consumer Protection Act, IT Act and RERA — and verifies every citation before showing it to you.",
  applicationName: "Adhikar",
  keywords: [
    "Indian law", "legal aid India", "BNS", "BNSS", "PWDVA",
    "Consumer Protection Act", "RERA", "NALSA", "free legal aid",
  ],
  authors: [{ name: "Akshay Kaushik" }],
  robots: { index: true, follow: true },
  openGraph: {
    title: "Adhikar — Know your rights",
    description: "AI-powered legal accessibility for India, with verified citations to official law.",
    type: "website",
    locale: "en_IN",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Never disable zoom: pinch-to-zoom is how many users with low vision read.
  maximumScale: 5,
  themeColor: "#0f172a",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN">
      <body className="min-h-dvh antialiased">
        {children}

        <footer className="mt-10 border-t border-[var(--line)] bg-[var(--surface)]">
          <div className="mx-auto w-full max-w-6xl space-y-4 px-4 py-8">
            <section aria-labelledby="footer-disclaimer">
              <h2 id="footer-disclaimer" className="font-bold">
                Legal disclaimer
              </h2>
              <p className="mt-1 max-w-3xl text-sm text-[var(--ink-muted)]">
                Adhikar provides AI-generated legal information for educational purposes only. It is
                not a substitute for professional legal advice, it does not create a
                lawyer&ndash;client relationship, and it cannot tell you how a court would decide
                your matter. For formal representation, consult a registered Advocate. Laws change,
                and several areas covered here — tenancy and police procedure especially — vary by
                State.
              </p>
            </section>

            <section aria-labelledby="footer-helplines">
              <h2 id="footer-helplines" className="font-bold">
                Emergency contacts
              </h2>
              <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
                {HELPLINES.map((helpline) => (
                  <li key={helpline.number} className="text-sm">
                    <a href={`tel:${helpline.number}`} className="font-bold underline underline-offset-2">
                      {helpline.number}
                    </a>{" "}
                    <span className="text-[var(--ink-muted)]">{helpline.name}</span>
                  </li>
                ))}
              </ul>
            </section>

            <p className="border-t border-[var(--line)] pt-4 text-xs text-[var(--ink-muted)]">
              Statutory text is published by the Government of India on{" "}
              <a
                href="https://www.indiacode.nic.in"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2"
              >
                India Code
              </a>
              . Adhikar is an independent open-source project and is not affiliated with any
              government body.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
