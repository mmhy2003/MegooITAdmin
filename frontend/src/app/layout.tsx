import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Orbitron } from "next/font/google";
import { themeBootstrapScript } from "@/lib/theme";
import "./globals.css";

// headings and text
const geist = Geist({ variable: "--font-geist", subsets: ["latin"] });
// code, IDs, commands and log lines
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
// the wordmark only
const orbitron = Orbitron({ variable: "--font-orbitron", subsets: ["latin"], weight: ["700"] });

export const metadata: Metadata = {
  title: { default: "MegooITAdmin", template: "%s · MegooITAdmin" },
  description: "Self-hosted IT administration with AI agents",
};

// the phone's status bar follows the theme's background
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f3ff" },
    { media: "(prefers-color-scheme: dark)", color: "#0e0f13" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geist.variable} ${geistMono.variable} ${orbitron.variable} antialiased`}
    >
      <head>
        {/* sets data-theme before the first paint so the page never flashes the wrong theme */}
        <script dangerouslySetInnerHTML={{ __html: themeBootstrapScript }} />
      </head>
      <body className="min-h-svh">{children}</body>
    </html>
  );
}
