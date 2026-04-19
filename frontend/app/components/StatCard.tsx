interface StatCardProps {
  label: string;
  value: string | number;
  unit?: string;
  sublabel?: string;
  color?: string;
}

export default function StatCard({ label, value, unit, sublabel, color = "accent" }: StatCardProps) {
  const colorMap: Record<string, string> = {
    accent: "text-accent",
    green: "text-accent-green",
    orange: "text-accent-orange",
    red: "text-accent-red",
  };

  return (
    <div className="bg-surface border border-border rounded-lg p-3 sm:p-4 flex flex-col gap-1" role="status" aria-label={`${label}: ${value} ${unit || ""}`}>
      <div className="text-[10px] sm:text-xs text-muted uppercase tracking-wider">
        {label}
      </div>
      <div className="flex items-baseline gap-1">
        <span className={`text-xl sm:text-2xl font-bold ${colorMap[color] || "text-accent"}`}>
          {value}
        </span>
        {unit && <span className="text-xs sm:text-sm text-muted">{unit}</span>}
      </div>
      {sublabel && <div className="text-[10px] sm:text-xs text-muted">{sublabel}</div>}
    </div>
  );
}
