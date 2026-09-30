import type { Metadata } from "next";
import "leaflet/dist/leaflet.css";
import "./globals.css";
import { AppProvider } from "@/lib/state";
import { Shell } from "@/components/Shell";
import { ToastProvider } from "@/components/forms";

export const metadata: Metadata = {
  title: "RoadGuard AI",
  description: "See the road. Understand the risk. Investigate every incident.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <AppProvider>
          <ToastProvider>
            <Shell>{children}</Shell>
          </ToastProvider>
        </AppProvider>
      </body>
    </html>
  );
}
