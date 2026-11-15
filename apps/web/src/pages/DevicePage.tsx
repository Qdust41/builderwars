import { Activity, BarChart3, Network, Radio, Table2, Timer } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { CommandList } from "../components/CommandList";
import { LogStream } from "../components/LogStream";
import { MetricChart } from "../components/MetricChart";
import {
  EmptyState,
  ErrorBanner,
  errorText,
  PageHeader,
  Skeleton,
  StatusPill,
  timeAgo,
} from "../components/ui";
import type { Sensor, TargetBoard, TelemetryValue } from "../api/types";
import { useSession } from "../auth/AuthGate";
import { SetupChain } from "../device/SetupChain";
import { BoardDialog, SensorDialog } from "../device/SetupDialogs";
import { describeMetric, formatValue, toSeries, type MetricMeta } from "../device/telemetry";
import { useDeviceLive, type LiveStatus } from "../device/useDeviceLive";
import { useAsync } from "../useAsync";

const LIVE: Record<LiveStatus, { text: string; dot: string; chip: string }> = {
  connecting: { text: "Connecting…", dot: "bg-warn", chip: "bg-warn-soft text-warn" },
  live: { text: "Live", dot: "bg-good live-pulse", chip: "bg-good-soft text-good" },
  reconnecting: { text: "Reconnecting…", dot: "bg-warn", chip: "bg-warn-soft text-warn" },
  offline: { text: "Live updates unavailable", dot: "bg-muted", chip: "bg-surface-2 text-muted" },
};

type Dialog =
  | { kind: "board"; board?: TargetBoard }
  | { kind: "sensor"; boardId: string; sensor?: Sensor };

/** How often the setup (laptop/FREE-WILi report, boards, sensors) is refetched. */
const SETUP_REFRESH_MS = 30_000;

export function DevicePage() {
  const { deviceId = "" } = useParams();
  const state = useDeviceLive(deviceId);
  const { device: d, samples } = state;
  const [asTable, setAsTable] = useState(false);
  const project = useAsync(
    () => (d ? api.getProject(d.project_id) : Promise.resolve(undefined)),
    [d?.project_id],
  );

  const session = useSession();
  const setup = useAsync(() => api.getDeviceSetup(deviceId), [deviceId]);
  const reloadSetup = setup.reload;
  useEffect(() => {
    const timer = window.setInterval(reloadSetup, SETUP_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [reloadSetup]);
  const [dialog, setDialog] = useState<Dialog>();
  // Boards and sensors are owner-only for now (the owner will open it to members later).
  const canEdit = !!project.data && project.data.owner_user_id === session?.user.userId;

  const series = useMemo(() => toSeries(samples), [samples]);
  const latest = useMemo(
    () => Object.fromEntries(series.map((s) => [s.name, s.latest])) as Record<string, TelemetryValue | undefined>,
    [series],
  );
  const meta = useMemo(() => {
    const out: Record<string, MetricMeta> = {};
    for (const s of setup.data?.sensors ?? []) out[s.key] = { label: s.name, unit: s.unit ?? "" };
    return out;
  }, [setup.data]);
  const charted = series.filter((s) => s.kind !== "text");
  const domain: [number, number] = samples.length
    ? [Date.parse(samples[0].ts), Date.parse(samples[samples.length - 1].ts)]
    : [0, 0];

  const crumbs = [
    { label: "Projects", to: "/" },
    ...(d ? [{ label: project.data?.name ?? "Project", to: `/projects/${d.project_id}` }] : []),
    { label: d?.display_name ?? "Device" },
  ];

  if (state.error) {
    return (
      <>
        <PageHeader title="Device" crumbs={crumbs} />
        <ErrorBanner>{errorText(state.error)}</ErrorBanner>
      </>
    );
  }

  const live = LIVE[state.live];
  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title={
          d ? (
            <span className="flex items-center gap-3">
              <span className="truncate">{d.display_name}</span>
              <StatusPill status={d.connection_status} />
            </span>
          ) : (
            <Skeleton className="h-8 w-56" />
          )
        }
        description={
          d && (
            <>
              {d.hardware_model}
              {d.extensions.length ? ` + ${d.extensions.join(", ")}` : ""} · firmware{" "}
              {d.firmware_version ?? "unknown"} · last seen {timeAgo(d.last_seen_at)}
            </>
          )
        }
        actions={
          <span
            className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium ${live.chip}`}
            title={state.liveError}
          >
            <span className={`size-2 rounded-full ${live.dot}`} aria-hidden="true" />
            {live.text}
          </span>
        }
      />

      <section className="card mb-6">
        <div className="card-head">
          <h2 className="card-title flex items-center gap-2">
            <Network className="size-4 text-muted" aria-hidden="true" />
            Test setup
          </h2>
          {!canEdit && project.data && (
            <span className="text-xs text-muted">Only the project owner can change boards and sensors.</span>
          )}
        </div>
        {setup.error ? (
          <div className="p-5">
            <ErrorBanner>{errorText(setup.error)}</ErrorBanner>
          </div>
        ) : (
          <SetupChain
            deviceId={deviceId}
            setup={setup.data}
            latest={latest}
            canEdit={canEdit}
            actions={{
              addBoard: () => setDialog({ kind: "board" }),
              editBoard: (board) => setDialog({ kind: "board", board }),
              addSensor: (board) => setDialog({ kind: "sensor", boardId: board.id }),
              editSensor: (sensor) => setDialog({ kind: "sensor", boardId: sensor.board_id, sensor }),
            }}
          />
        )}
      </section>

      {dialog?.kind === "board" && (
        <BoardDialog
          deviceId={deviceId}
          board={dialog.board}
          sensorCount={(setup.data?.sensors ?? []).filter((s) => s.board_id === dialog.board?.id).length}
          onClose={() => setDialog(undefined)}
          onSaved={reloadSetup}
        />
      )}
      {dialog?.kind === "sensor" && setup.data && (
        <SensorDialog
          deviceId={deviceId}
          boards={setup.data.boards}
          boardId={dialog.boardId}
          sensor={dialog.sensor}
          onClose={() => setDialog(undefined)}
          onSaved={reloadSetup}
        />
      )}

      {series.length > 0 && (
        <dl className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {series.slice(0, 8).map((s) => {
            const { label, unit } = describeMetric(s.name, meta);
            return (
              <div key={s.name} className="card px-4 py-3.5">
                <dt className="truncate text-xs font-medium text-muted">{label}</dt>
                <dd className="mt-1 truncate text-xl font-semibold tabular-nums tracking-tight text-fg">
                  {formatValue(s.latest, s.kind === "number" ? unit : "")}
                </dd>
              </div>
            );
          })}
        </dl>
      )}

      <section className="card mb-6">
        <div className="card-head">
          <h2 className="card-title flex items-center gap-2">
            <Activity className="size-4 text-muted" aria-hidden="true" />
            Telemetry
          </h2>
          {series.length > 0 && (
            <div className="flex rounded-lg border border-line bg-surface-2 p-0.5 text-xs font-medium" role="group">
              <button
                className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 ${!asTable ? "bg-surface text-fg shadow-sm" : "text-muted"}`}
                aria-pressed={!asTable}
                onClick={() => setAsTable(false)}
              >
                <BarChart3 className="size-3.5" aria-hidden="true" /> Charts
              </button>
              <button
                className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 ${asTable ? "bg-surface text-fg shadow-sm" : "text-muted"}`}
                aria-pressed={asTable}
                onClick={() => setAsTable(true)}
              >
                <Table2 className="size-3.5" aria-hidden="true" /> Table
              </button>
            </div>
          )}
        </div>
        {series.length === 0 ? (
          <EmptyState icon={<Radio className="size-5" />} title="Waiting for telemetry">
            <p>
              Sign in to the CLI on the laptop the FREE-WILi is plugged into and run{" "}
              <code className="font-mono text-xs">builderwars run --cloud --device-id {deviceId}</code>. It reads the
              sensors defined above (add <code className="font-mono text-xs">--simulate</code> without a board).
            </p>
          </EmptyState>
        ) : asTable ? (
          <TelemetryTable samples={samples} names={series.map((s) => s.name)} meta={meta} />
        ) : (
          <div className="p-5">
            {charted.length > 0 ? (
              <div className="grid gap-x-8 gap-y-6 md:grid-cols-2">
                {charted.map((s) => (
                  <MetricChart key={s.name} series={s} domain={domain} meta={meta} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted">This device only reports text readings (shown above).</p>
            )}
            <p className="mt-5 flex items-center gap-1.5 text-xs text-muted">
              <Timer className="size-3.5" aria-hidden="true" />
              {samples.length} samples · {new Date(domain[0]).toLocaleTimeString()} to{" "}
              {new Date(domain[1]).toLocaleTimeString()}
            </p>
          </div>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-5">
        <section className="card lg:col-span-2">
          <div className="card-head">
            <h2 className="card-title">Commands</h2>
            <div className="flex gap-2">
              <button className="btn-primary px-3 py-1.5" onClick={() => state.sendCommand("ping")} disabled={!d}>
                Send ping
              </button>
              <button
                className="btn-secondary px-3 py-1.5"
                onClick={() => state.sendCommand("get_uptime")}
                disabled={!d}
              >
                Get uptime
              </button>
            </div>
          </div>
          {state.commandError && (
            <div className="px-5 pt-4">
              <ErrorBanner>{errorText(state.commandError)}</ErrorBanner>
            </div>
          )}
          <CommandList commands={state.commands} />
        </section>
        <section className="card overflow-hidden lg:col-span-3">
          <div className="card-head">
            <h2 className="card-title">Logs</h2>
            <span className="text-xs text-muted">{state.logs.length} lines</span>
          </div>
          <LogStream entries={state.logs} />
        </section>
      </div>
    </>
  );
}

function TelemetryTable({
  samples,
  names,
  meta,
}: {
  samples: { ts: string; readings: Record<string, number | boolean | string> }[];
  names: string[];
  meta: Record<string, MetricMeta>;
}) {
  const rows = samples.slice(-100).reverse();
  return (
    <div>
      <div className="max-h-[28rem] overflow-auto">
        <table className="w-full text-left text-sm tabular-nums">
          <thead className="sticky top-0 bg-surface-2 text-xs font-medium text-muted">
            <tr>
              <th className="px-5 py-2.5 font-medium">Time</th>
              {names.map((n) => {
                const { label, unit } = describeMetric(n, meta);
                return (
                  <th key={n} className="px-4 py-2.5 font-medium whitespace-nowrap">
                    {unit ? `${label} (${unit})` : label}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((s) => (
              <tr key={s.ts} className="hover:bg-surface-2">
                <td className="px-5 py-2 whitespace-nowrap text-muted">{new Date(s.ts).toLocaleTimeString()}</td>
                {names.map((n) => (
                  <td key={n} className="px-4 py-2 whitespace-nowrap text-fg">
                    {formatValue(s.readings[n])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {samples.length > 100 && (
        <p className="border-t border-line px-5 py-2.5 text-xs text-muted">Newest 100 of {samples.length}.</p>
      )}
    </div>
  );
}
