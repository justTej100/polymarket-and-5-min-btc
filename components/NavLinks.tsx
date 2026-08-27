"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/board", label: "Board" },
  { href: "/leaderboard", label: "Leaderboard" },
  { href: "/strategy", label: "Strategy" },
];

export function NavLinks() {
  const pathname = usePathname();
  return (
    <div className="nav__links">
      {LINKS.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className={`nav__link ${pathname === link.href ? "nav__link--active" : ""}`}
        >
          {link.label}
        </Link>
      ))}
    </div>
  );
}
