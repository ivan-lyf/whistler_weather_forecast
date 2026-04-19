"use client";

import { useEffect, useState } from "react";

export interface ThemeColors {
  background: string;
  foreground: string;
  surface: string;
  border: string;
  muted: string;
}

const DARK_DEFAULTS: ThemeColors = {
  background: "#0a0e14",
  foreground: "#c5cbd3",
  surface: "#0d1117",
  border: "#1e2530",
  muted: "#6b7280",
};

const LIGHT_DEFAULTS: ThemeColors = {
  background: "#f8f9fa",
  foreground: "#1a1a2e",
  surface: "#ffffff",
  border: "#dde1e6",
  muted: "#6b7280",
};

export function useThemeColors(): ThemeColors {
  const [colors, setColors] = useState<ThemeColors>(DARK_DEFAULTS);

  useEffect(() => {
    function update() {
      const style = getComputedStyle(document.documentElement);
      setColors({
        background: style.getPropertyValue("--background").trim() || DARK_DEFAULTS.background,
        foreground: style.getPropertyValue("--foreground").trim() || DARK_DEFAULTS.foreground,
        surface: style.getPropertyValue("--surface").trim() || DARK_DEFAULTS.surface,
        border: style.getPropertyValue("--border").trim() || DARK_DEFAULTS.border,
        muted: style.getPropertyValue("--muted").trim() || DARK_DEFAULTS.muted,
      });
    }

    update();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  return colors;
}
