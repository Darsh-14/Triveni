import type { Metadata } from "next";
import { IBM_Plex_Mono } from "next/font/google";
import localFont from "next/font/local";
import "./globals.css";

// TeX Gyre Heros: a free, metric-compatible Helvetica (GUST Font License, see src/fonts/tex-gyre-heros).
// Neue Helvetica itself is a paid Linotype face.
const heros = localFont({
  variable: "--font-heros",
  src: [
    { path: "../fonts/tex-gyre-heros/texgyreheros-regular.otf", weight: "400", style: "normal" },
    { path: "../fonts/tex-gyre-heros/texgyreheros-italic.otf", weight: "400", style: "italic" },
    { path: "../fonts/tex-gyre-heros/texgyreheros-bold.otf", weight: "700", style: "normal" },
    { path: "../fonts/tex-gyre-heros/texgyreheros-bolditalic.otf", weight: "700", style: "italic" },
  ],
  fallback: ["Helvetica Neue", "Helvetica", "Arial", "sans-serif"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "Triveni",
  description: "Engineering Company Brain on FalkorDB: agents act, remember, and prove every answer with a path.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${heros.variable} ${plexMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
