"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Header() {
  const pathname = usePathname();
  const isDetails = pathname === "/details";

  return (
    <header className="border-b border-border bg-surface px-4 sm:px-6 py-3 sm:py-4">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        <Link href="/" className="flex items-center gap-3 hover:opacity-80 transition-opacity">
          <div className="w-2 h-2 rounded-full bg-accent-green animate-pulse" aria-hidden="true" />
          <h1 className="text-base sm:text-lg font-bold tracking-tight text-foreground">
            whistler_forecast<span className="text-muted">.v1</span>
          </h1>
        </Link>
        <nav className="flex items-center gap-3 sm:gap-4 text-[10px] sm:text-xs" aria-label="Main navigation">
          <Link
            href="/"
            className={`transition-colors ${!isDetails ? "text-accent" : "text-muted hover:text-foreground"}`}
          >
            Forecast
          </Link>
          <span className="text-border" aria-hidden="true">|</span>
          <Link
            href="/details"
            className={`transition-colors ${isDetails ? "text-accent" : "text-muted hover:text-foreground"}`}
          >
            Details
          </Link>
          <span className="text-border hidden sm:inline" aria-hidden="true">|</span>
          <span className="hidden sm:inline text-muted">50.099°N · 2200m</span>
        </nav>
      </div>
    </header>
  );
}
