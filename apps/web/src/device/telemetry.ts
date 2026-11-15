import type { DeviceLogEntry, TelemetrySample, TelemetryValue } from "../api/types";

/** How many samples / log lines the dashboard keeps in memory. */
export const MAX_SAMPLES = 600;
export const MAX_LOG_ENTRIES = 300;

/** Merge samples by timestamp (later copies win), oldest first, keeping the newest `max`. */
export function mergeSamples(
  current: TelemetrySample[],
  incoming: TelemetrySample[],
  max = MAX_SAMPLES,
): TelemetrySample[] {
  if (incoming.length === 0) return current;
  const byTs = new Map<string, TelemetrySample>();
  for (const s of current) byTs.set(s.ts, s);
  for (const s of incoming) byTs.set(s.ts, s);
  const merged = [...byTs.values()].sort((a, b) => Date.parse(a.ts) - Date.parse(b.ts));
  return merged.slice(-max);
}

/** Merge log entries (a refetch and live events can overlap), oldest first, newest `max`. */
export function mergeLogs(
  current: DeviceLogEntry[],
  incoming: DeviceLogEntry[],
  max = MAX_LOG_ENTRIES,
): DeviceLogEntry[] {
  if (incoming.length === 0) return current;
  const key = (e: DeviceLogEntry) => `${e.at}|${e.kind}|${e.level}|${e.message}`;
  const seen = new Set(current.map(key));
  const merged = [...current];
  for (const e of incoming) {
    if (!seen.has(key(e))) {
      seen.add(key(e));
      merged.push(e);
    }
  }
  merged.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  return merged.slice(-max);
}

export type MetricKind = "number" | "boolean" | "text";

export interface MetricPoint {
  t: number; // epoch ms
  v: number; // booleans as 0/1
}

export interface MetricSeries {
  name: string;
  kind: MetricKind;
  points: MetricPoint[];
  latest: TelemetryValue | undefined;
  latestAt: number | undefined;
}

/**
 * One series per reading name, in first-seen order. A reading's kind comes from its latest
 * value; text readings get no points (they are shown as a latest value only).
 */
export function toSeries(samples: TelemetrySample[]): MetricSeries[] {
  const series = new Map<string, MetricSeries>();
  for (const sample of samples) {
    const t = Date.parse(sample.ts);
    for (const [name, value] of Object.entries(sample.readings)) {
      let s = series.get(name);
      if (!s) {
        s = { name, kind: kindOf(value), points: [], latest: undefined, latestAt: undefined };
        series.set(name, s);
      }
      s.kind = kindOf(value);
      s.latest = value;
      s.latestAt = t;
      if (typeof value === "number" && Number.isFinite(value)) s.points.push({ t, v: value });
      else if (typeof value === "boolean") s.points.push({ t, v: value ? 1 : 0 });
    }
  }
  return [...series.values()];
}

function kindOf(value: TelemetryValue): MetricKind {
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return "number";
  return "text";
}

/** "temperature_c" -> { label: "Temperature", unit: "°C" }. Unknown suffixes stay in the label. */
export function describeMetric(name: string): { label: string; unit: string } {
  const units: [string, string][] = [
    ["_pct", "%"],
    ["_c", "°C"],
    ["_v", "V"],
    ["_mv", "mV"],
    ["_ma", "mA"],
    ["_kb", "KB"],
    ["_ms", "ms"],
    ["_s", "s"],
    ["_hz", "Hz"],
  ];
  for (const [suffix, unit] of units) {
    if (name.endsWith(suffix)) return { label: humanize(name.slice(0, -suffix.length)), unit };
  }
  return { label: humanize(name), unit: "" };
}

const ACRONYMS = new Set(["cpu", "gpio", "io", "adc", "led", "rssi", "i2c", "spi", "uart"]);

function humanize(name: string): string {
  const words = name
    .split(/[_-]+/)
    .filter(Boolean)
    .map((w) => (ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w));
  const text = words.join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function formatValue(value: TelemetryValue | undefined, unit = ""): string {
  if (value === undefined) return "–";
  if (typeof value === "boolean") return value ? "On" : "Off";
  if (typeof value === "number") {
    const abs = Math.abs(value);
    const text =
      Number.isInteger(value) || abs >= 1000
        ? Math.round(value).toLocaleString()
        : value.toFixed(abs >= 100 ? 1 : 2);
    return unit ? `${text} ${unit}` : text;
  }
  return value;
}

/** Axis labels: no padding zeros ("37.5", not "37.50"). */
export function formatTick(value: number): string {
  return Number(value.toPrecision(6)).toLocaleString();
}

/** Up to `count` round tick values covering [min, max]. */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) return [min];
  const span = max - min;
  const raw = span / Math.max(1, count - 1);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count - 1) ?? 10 * mag;
  const start = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let i = 0; i < 20; i++) {
    const v = Number((start + i * step).toPrecision(12));
    ticks.push(v);
    if (v >= max) break;
  }
  return ticks;
}
