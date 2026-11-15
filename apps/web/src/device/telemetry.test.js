import { describe, expect, it } from "vitest";
import { describeMetric, formatTick, formatValue, mergeLogs, mergeSamples, niceTicks, toSeries } from "./telemetry";
const sample = (sec, readings) => ({
    ts: new Date(Date.UTC(2026, 10, 14, 20, 0, sec)).toISOString(),
    readings,
});
describe("mergeSamples", () => {
    it("dedupes by timestamp, sorts oldest first and keeps the newest max", () => {
        const merged = mergeSamples([sample(2, { t: 2 }), sample(1, { t: 1 })], [sample(2, { t: 20 }), sample(3, { t: 3 })], 2);
        expect(merged.map((s) => s.readings.t)).toEqual([20, 3]);
    });
    it("returns the same array when nothing arrives", () => {
        const current = [sample(1, { t: 1 })];
        expect(mergeSamples(current, [])).toBe(current);
    });
});
describe("mergeLogs", () => {
    it("drops entries a refetch and a live event both delivered", () => {
        const line = { at: sample(1, {}).ts, kind: "log", level: "info", message: "hi" };
        const later = { ...line, at: sample(2, {}).ts };
        expect(mergeLogs([line], [later, line])).toEqual([line, later]);
    });
});
describe("toSeries", () => {
    it("makes one series per reading, booleans as 0/1, text without points", () => {
        const series = toSeries([
            sample(1, { temperature_c: 40.5, button: true, mode: "idle" }),
            sample(2, { temperature_c: 41, button: false, mode: "run" }),
        ]);
        expect(series.map((s) => [s.name, s.kind])).toEqual([
            ["temperature_c", "number"],
            ["button", "boolean"],
            ["mode", "text"],
        ]);
        expect(series[1].points.map((p) => p.v)).toEqual([1, 0]);
        expect(series[2].points).toEqual([]);
        expect(series[2].latest).toBe("run");
    });
});
describe("labels", () => {
    it("reads units and acronyms from reading names", () => {
        expect(describeMetric("temperature_c")).toEqual({ label: "Temperature", unit: "°C" });
        expect(describeMetric("cpu_load_pct")).toEqual({ label: "CPU load", unit: "%" });
        expect(describeMetric("gpio_3")).toEqual({ label: "GPIO 3", unit: "" });
    });
    it("formats values and ticks", () => {
        expect(formatValue(true)).toBe("On");
        expect(formatValue(undefined)).toBe("–");
        expect(formatValue(41.234, "°C")).toBe("41.23 °C");
        expect(formatTick(37.5)).toBe("37.5");
    });
    it("picks round ticks that cover the range", () => {
        const ticks = niceTicks(37.4, 42.6, 4);
        expect(ticks[0]).toBeLessThanOrEqual(37.4);
        expect(ticks.at(-1)).toBeGreaterThanOrEqual(42.6);
        expect(ticks.length).toBeLessThanOrEqual(5);
        expect(niceTicks(5, 5)).toEqual([5]);
    });
});
