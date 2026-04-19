"use client";

import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL;
if (!API) {
  throw new Error("NEXT_PUBLIC_API_URL is not set. Define it in .env.local (dev) or the hosting provider's env vars (prod).");
}

const TARGETS = [
  { value: "snowfall_24h", label: "24h Snowfall (cm)", defaultThreshold: 10 },
  { value: "wind_6h", label: "6h Max Wind (km/h)", defaultThreshold: 50 },
  { value: "wind_12h", label: "12h Max Wind (km/h)", defaultThreshold: 60 },
  { value: "freezing_level", label: "Freezing Level (m)", defaultThreshold: 1500 },
];

const LOCATIONS = [
  { value: "alpine", label: "Alpine 2200m" },
  { value: "mid", label: "Mid 1500m" },
  { value: "base", label: "Base 675m" },
];

type Step = "subscribe" | "rules" | "done";

export default function AlertSubscribe() {
  const [step, setStep] = useState<Step>("subscribe");
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [location, setLocation] = useState("alpine");
  const [target, setTarget] = useState("snowfall_24h");
  const [operator, setOperator] = useState(">");
  const [threshold, setThreshold] = useState(10);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rules, setRules] = useState<Array<{ id: number; target_name: string; operator: string; threshold: number }>>([]);

  async function handleSubscribe(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const res = await fetch(`${API}/api/alerts/subscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone_number: phone, name: name || undefined, location }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Subscribe failed");
      setStatus(data.status === "subscribed" ? "Subscribed!" : data.status === "reactivated" ? "Reactivated!" : "Already subscribed");
      setStep("rules");
      loadRules();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  async function handleAddRule(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const res = await fetch(`${API}/api/alerts/rules`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone_number: phone, target_name: target, operator, threshold }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to add rule");
      setStatus(`Rule added: ${target} ${operator} ${threshold}`);
      loadRules();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed");
    }
  }

  async function loadRules() {
    try {
      const res = await fetch(`${API}/api/alerts/rules/${encodeURIComponent(phone)}`);
      if (res.ok) {
        const data = await res.json();
        setRules(data.rules || []);
      }
    } catch { /* ignore */ }
  }

  async function deleteRule(id: number) {
    try {
      await fetch(`${API}/api/alerts/rules/${id}`, { method: "DELETE" });
      loadRules();
    } catch { /* ignore */ }
  }

  async function handleUnsubscribe() {
    try {
      const res = await fetch(`${API}/api/alerts/unsubscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone_number: phone }),
      });
      if (res.ok) {
        setStatus("Unsubscribed");
        setStep("subscribe");
        setRules([]);
      }
    } catch { /* ignore */ }
  }

  return (
    <div className="bg-surface border border-border rounded-lg p-3 sm:p-4">
      <div className="text-[10px] sm:text-xs text-muted uppercase tracking-wider mb-3">
        SMS Weather Alerts
      </div>

      {error && (
        <div className="bg-accent-red/10 border border-accent-red/30 rounded p-2 text-accent-red text-xs mb-3" role="alert">
          {error}
        </div>
      )}

      {status && (
        <div className="bg-accent-green/10 border border-accent-green/30 rounded p-2 text-accent-green text-xs mb-3" role="status">
          {status}
        </div>
      )}

      {step === "subscribe" && (
        <form onSubmit={handleSubscribe} className="flex flex-col gap-3">
          <p className="text-xs text-muted">Get text alerts when weather thresholds are met.</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <input
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+1234567890"
              required
              aria-label="Phone number"
              className="bg-background border border-border rounded px-3 py-2 text-xs text-foreground placeholder:text-muted focus:outline-none focus:border-accent"
            />
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Name (optional)"
              aria-label="Name"
              className="bg-background border border-border rounded px-3 py-2 text-xs text-foreground placeholder:text-muted focus:outline-none focus:border-accent"
            />
            <select
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              aria-label="Location"
              className="bg-background border border-border rounded px-3 py-2 text-xs text-foreground focus:outline-none focus:border-accent"
            >
              {LOCATIONS.map((l) => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </select>
          </div>
          <button
            type="submit"
            className="bg-accent/20 text-accent border border-accent/30 rounded px-4 py-2 text-xs font-bold uppercase tracking-wider hover:bg-accent/30 transition-colors w-fit"
          >
            Subscribe
          </button>
        </form>
      )}

      {step === "rules" && (
        <div className="flex flex-col gap-3">
          <p className="text-xs text-muted">Subscribed as <span className="text-foreground">{phone}</span>. Add alert rules below.</p>

          {/* Existing rules */}
          {rules.length > 0 && (
            <div className="flex flex-col gap-1">
              {rules.map((r) => (
                <div key={r.id} className="flex items-center justify-between bg-background/50 rounded px-3 py-1.5 text-xs">
                  <span className="text-foreground">
                    {r.target_name} {r.operator} {r.threshold}
                  </span>
                  <button onClick={() => deleteRule(r.id)} className="text-accent-red hover:text-accent-red/80 text-[10px]" aria-label={`Delete rule ${r.target_name}`}>
                    remove
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Add rule form */}
          <form onSubmit={handleAddRule} className="flex flex-wrap items-end gap-2">
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-muted">Alert when</label>
              <select
                value={target}
                onChange={(e) => {
                  setTarget(e.target.value);
                  const t = TARGETS.find((t) => t.value === e.target.value);
                  if (t) setThreshold(t.defaultThreshold);
                }}
                className="bg-background border border-border rounded px-2 py-1.5 text-xs text-foreground"
              >
                {TARGETS.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <select
              value={operator}
              onChange={(e) => setOperator(e.target.value)}
              className="bg-background border border-border rounded px-2 py-1.5 text-xs text-foreground"
              aria-label="Operator"
            >
              <option value=">">&gt;</option>
              <option value=">=">&gt;=</option>
              <option value="<">&lt;</option>
              <option value="<=">&lt;=</option>
            </select>
            <input
              type="number"
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              step="any"
              className="bg-background border border-border rounded px-2 py-1.5 text-xs text-foreground w-20"
              aria-label="Threshold value"
            />
            <button
              type="submit"
              className="bg-accent/20 text-accent border border-accent/30 rounded px-3 py-1.5 text-xs font-bold hover:bg-accent/30 transition-colors"
            >
              Add Rule
            </button>
          </form>

          <div className="flex gap-3 mt-1">
            <button
              onClick={() => setStep("done")}
              className="text-xs text-accent hover:text-accent/80"
            >
              Done
            </button>
            <button
              onClick={handleUnsubscribe}
              className="text-xs text-muted hover:text-accent-red"
            >
              Unsubscribe
            </button>
          </div>
        </div>
      )}

      {step === "done" && (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-muted">
            Alerts active for <span className="text-foreground">{phone}</span> — {rules.length} rule{rules.length !== 1 ? "s" : ""} configured.
          </p>
          <div className="flex gap-3">
            <button onClick={() => setStep("rules")} className="text-xs text-accent hover:text-accent/80">
              Edit rules
            </button>
            <button onClick={() => { setStep("subscribe"); setPhone(""); setRules([]); setStatus(null); }} className="text-xs text-muted hover:text-foreground">
              Different number
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
