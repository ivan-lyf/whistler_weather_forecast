export default function Header() {
  return (
    <header className="border-b border-border bg-surface px-6 py-4">
      <div className="max-w-7xl mx-auto flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-accent-green animate-pulse" />
          <h1 className="text-lg font-bold tracking-tight text-foreground">
            whistler_forecast<span className="text-muted">.v1</span>
          </h1>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted">
          <span>ML-corrected alpine weather</span>
          <span className="text-border">|</span>
          <span>50.099&deg;N 122.942&deg;W</span>
          <span className="text-border">|</span>
          <span>2200m</span>
        </div>
      </div>
    </header>
  );
}
