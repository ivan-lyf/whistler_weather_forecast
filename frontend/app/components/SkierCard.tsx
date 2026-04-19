interface TimeRow {
  label: string;
  value: number | null;
}

interface SkierCardProps {
  title: string;
  unit: string;
  rows: TimeRow[];
  color?: string;
  icon?: string;
}

export default function SkierCard({ title, unit, rows, color = "accent", icon }: SkierCardProps) {
  const colorMap: Record<string, string> = {
    accent: "text-accent",
    green: "text-accent-green",
    orange: "text-accent-orange",
    red: "text-accent-red",
  };
  const cls = colorMap[color] || "text-accent";

  return (
    <div className="bg-surface border border-border rounded-lg p-4 sm:p-5" role="status" aria-label={title}>
      <div className="flex items-center gap-2 mb-3">
        {icon && <span className="text-lg">{icon}</span>}
        <span className="text-xs text-muted uppercase tracking-wider font-bold">{title}</span>
      </div>
      <div className="flex flex-col gap-2">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between">
            <span className="text-xs text-muted">{r.label}</span>
            <div className="flex items-baseline gap-1">
              <span className={`text-lg sm:text-xl font-bold tabular-nums ${cls}`}>
                {r.value !== null ? r.value.toFixed(1) : "—"}
              </span>
              <span className="text-[10px] text-muted">{unit}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
