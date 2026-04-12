interface ModelMetric {
  name: string;
  target: string;
  testMae?: number;
  testRmse?: number;
  testAcc?: number;
  bestBaseline: string;
  baselineValue: number;
  improvement: string;
}

const MODELS: ModelMetric[] = [
  {
    name: "snowfall_24h",
    target: "24h Snowfall (cm)",
    testMae: 0.805,
    testRmse: 1.943,
    bestBaseline: "Raw GFS",
    baselineValue: 1.742,
    improvement: "53.8%",
  },
  {
    name: "wind_6h",
    target: "6h Wind (km/h)",
    testMae: 1.261,
    testRmse: 1.850,
    bestBaseline: "Persistence",
    baselineValue: 8.229,
    improvement: "84.7%",
  },
  {
    name: "wind_12h",
    target: "12h Wind (km/h)",
    testMae: 1.142,
    testRmse: 1.803,
    bestBaseline: "Climatology",
    baselineValue: 9.100,
    improvement: "87.5%",
  },
  {
    name: "freezing_level",
    target: "Freezing Level (m)",
    testMae: 131.1,
    testRmse: 169.0,
    bestBaseline: "Climatology",
    baselineValue: 379.2,
    improvement: "65.4%",
  },
  {
    name: "precip_type",
    target: "Precip Type",
    testAcc: 0.960,
    bestBaseline: "Persistence",
    baselineValue: 0.938,
    improvement: "+2.2%",
  },
];

export default function MetricsTable() {
  return (
    <div className="bg-surface border border-border rounded-lg p-4">
      <div className="text-xs text-muted uppercase tracking-wider mb-3">
        Model Performance — Test Period (Jul-Dec 2025)
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted border-b border-border">
              <th className="text-left py-2 pr-4">Target</th>
              <th className="text-right py-2 px-3">MAE</th>
              <th className="text-right py-2 px-3">RMSE</th>
              <th className="text-right py-2 px-3">Accuracy</th>
              <th className="text-right py-2 px-3">Baseline</th>
              <th className="text-right py-2 px-3">Baseline MAE</th>
              <th className="text-right py-2 pl-3">Improvement</th>
            </tr>
          </thead>
          <tbody>
            {MODELS.map((m) => (
              <tr key={m.name} className="border-b border-border/50 hover:bg-surface-2">
                <td className="py-2 pr-4 text-foreground">{m.target}</td>
                <td className="text-right py-2 px-3 text-accent">
                  {m.testMae?.toFixed(1) ?? "—"}
                </td>
                <td className="text-right py-2 px-3 text-muted">
                  {m.testRmse?.toFixed(1) ?? "—"}
                </td>
                <td className="text-right py-2 px-3 text-accent">
                  {m.testAcc ? `${(m.testAcc * 100).toFixed(1)}%` : "—"}
                </td>
                <td className="text-right py-2 px-3 text-muted">{m.bestBaseline}</td>
                <td className="text-right py-2 px-3 text-muted">
                  {m.baselineValue < 1 ? `${(m.baselineValue * 100).toFixed(1)}%` : m.baselineValue.toFixed(1)}
                </td>
                <td className="text-right py-2 pl-3 text-accent-green font-bold">
                  {m.improvement}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
