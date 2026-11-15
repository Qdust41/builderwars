import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CommandList } from "../components/CommandList";
import { LogStream } from "../components/LogStream";
import { MetricChart } from "../components/MetricChart";
import { describeMetric, formatValue, toSeries } from "../device/telemetry";
import { useDeviceLive, type LiveStatus } from "../device/useDeviceLive";

const LIVE_TEXT: Record<LiveStatus, string> = {
  connecting: "Connecting…",
  live: "Live",
  reconnecting: "Reconnecting…",
  offline: "Live updates unavailable",
};

export function DevicePage() {
  const { deviceId = "" } = useParams();
  const state = useDeviceLive(deviceId);
  const { device: d, samples } = state;
  const [asTable, setAsTable] = useState(false);

  const series = useMemo(() => toSeries(samples), [samples]);
  const charted = series.filter((s) => s.kind !== "text");
  const textOnly = series.filter((s) => s.kind === "text");
  const domain: [number, number] = samples.length
    ? [Date.parse(samples[0].ts), Date.parse(samples[samples.length - 1].ts)]
    : [0, 0];

  if (state.error) return <p className="error">{state.error}</p>;
  return (
    <section className="device">
      <header className="device-header">
        <div>
          {d && (
            <Link className="crumb" to={`/projects/${d.project_id}`}>
              ← Project
            </Link>
          )}
          <h1>{d?.display_name ?? "…"}</h1>
          <p className="muted">
            {d?.hardware_model}
            {d?.extensions.length ? ` + ${d.extensions.join(", ")}` : ""} · firmware{" "}
            {d?.firmware_version ?? "unknown"}
          </p>
        </div>
        <div className="device-status">
          <span className={`pill pill-${d?.connection_status ?? "unknown"}`}>
            {d?.connection_status ?? "unknown"}
          </span>
          <span className="muted">
            Last seen{" "}
            {d?.last_seen_at ? new Date(d.last_seen_at).toLocaleTimeString() : "never"}
          </span>
          <span className={`live live-${state.live}`} title={state.liveError}>
            <span className="live-dot" aria-hidden="true" />
            {LIVE_TEXT[state.live]}
          </span>
        </div>
      </header>

      <div className="panel">
        <div className="panel-head">
          <h2>Telemetry</h2>
          {series.length > 0 && (
            <button className="link" onClick={() => setAsTable((v) => !v)}>
              {asTable ? "Show charts" : "Show as table"}
            </button>
          )}
        </div>
        {series.length === 0 ? (
          <p className="muted">
            No telemetry yet. Start the host runtime (or the simulator) for this device and
            readings appear here as they arrive.
          </p>
        ) : asTable ? (
          <TelemetryTable samples={samples} names={series.map((s) => s.name)} />
        ) : (
          <>
            <div className="metrics">
              {charted.map((s) => (
                <MetricChart key={s.name} series={s} domain={domain} />
              ))}
            </div>
            {textOnly.length > 0 && (
              <dl className="text-readings">
                {textOnly.map((s) => (
                  <div key={s.name}>
                    <dt>{describeMetric(s.name).label}</dt>
                    <dd>{formatValue(s.latest)}</dd>
                  </div>
                ))}
              </dl>
            )}
            <p className="muted small">
              {samples.length} samples · {new Date(domain[0]).toLocaleTimeString()} to{" "}
              {new Date(domain[1]).toLocaleTimeString()}
            </p>
          </>
        )}
      </div>

      <div className="columns">
        <div className="panel">
          <div className="panel-head">
            <h2>Commands</h2>
          </div>
          <div className="actions">
            <button onClick={() => state.sendCommand("ping")} disabled={!d}>
              Send ping
            </button>
            <button
              className="secondary"
              onClick={() => state.sendCommand("get_uptime")}
              disabled={!d}
            >
              Get uptime
            </button>
          </div>
          {state.commandError && <p className="error">{state.commandError}</p>}
          <CommandList commands={state.commands} />
        </div>
        <div className="panel">
          <div className="panel-head">
            <h2>Logs</h2>
          </div>
          <LogStream entries={state.logs} />
        </div>
      </div>
    </section>
  );
}

function TelemetryTable({
  samples,
  names,
}: {
  samples: { ts: string; readings: Record<string, number | boolean | string> }[];
  names: string[];
}) {
  const rows = samples.slice(-100).reverse();
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            {names.map((n) => {
              const { label, unit } = describeMetric(n);
              return <th key={n}>{unit ? `${label} (${unit})` : label}</th>;
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => (
            <tr key={s.ts}>
              <td>{new Date(s.ts).toLocaleTimeString()}</td>
              {names.map((n) => (
                <td key={n}>{formatValue(s.readings[n])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {samples.length > 100 && <p className="muted small">Newest 100 of {samples.length}.</p>}
    </div>
  );
}
