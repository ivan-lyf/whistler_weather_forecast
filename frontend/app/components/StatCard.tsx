interface StatCardProps {
  label: string;
  value: string | number;
  unit?: string;
  sublabel?: string;
  color?: string;
  icon?: string;
}

export default function StatCard({ label, value, unit, sublabel, color = "accent", icon }: StatCardProps) {
  const colorMap: Record<string, string> = {
    accent: "text-accent",
    green: "text-accent-green",
    orange: "text-accent-orange",
    red: "text-accent-red",
  };

  return (
    <div className="bg-surface border border-border rounded-lg p-4 flex flex-col gap-1">
      <div className="text-xs text-muted uppercase tracking-wider flex items-center gap-2">
        {icon && <span>{icon}</span>}
        {label}
      </div>
      <div className="flex items-baseline gap-1">
        <span className={`text-2xl font-bold ${colorMap[color] || "text-accent"}`}>
          {value}
        </span>
        {unit && <span className="text-sm text-muted">{unit}</span>}
      </div>
      {sublabel && <div className="text-xs text-muted">{sublabel}</div>}
    </div>
  );
}
