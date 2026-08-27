import "./globals.css";
import { NavLinks } from "@/components/NavLinks";

export const metadata = {
  title: "Polymarket Strategy Board",
  description:
    "Rule-based strategies watching Polymarket's BTC 5-min Up/Down markets, live and simulated.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="nav-bar">
          <nav className="nav">
          
            <NavLinks />
          </nav>
        </div>
        <div className="shell">{children}</div>
      </body>
    </html>
  );
}
