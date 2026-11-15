import {
  ArrowDown,
  ArrowRight,
  CircuitBoard,
  Cpu,
  Laptop,
  Pencil,
  Plus,
  Usb,
} from "lucide-react";
import type { ReactNode } from "react";
import type { DeviceSetup, Sensor, TargetBoard, TelemetryValue } from "../api/types";
import { timeAgo } from "../components/ui";
import { formatValue } from "./telemetry";
import { describeBus } from "./sensors";

export interface SetupActions {
  addBoard: () => void;
  editBoard: (board: TargetBoard) => void;
  addSensor: (board: TargetBoard) => void;
  editSensor: (sensor: Sensor) => void;
}

const SOURCE_TEXT: Record<string, string> = {
  freewili: "Reading this device's sensors",
  "freewili-gpio": "No sensors defined: sending the FREE-WILi's own pins",
  simulated: "Simulated values (--simulate), no board is read",
};

/**
 * The physical chain behind a device: the laptop running the CLI, the FREE-WILi on its USB
 * port, and up to 4 target boards wired to the FREE-WILi, each with its sensors.
 */
export function SetupChain({
  deviceId,
  setup,
  latest,
  canEdit,
  actions,
}: {
  deviceId: string;
  setup: DeviceSetup | undefined;
  latest: Record<string, TelemetryValue | undefined>;
  canEdit: boolean;
  actions: SetupActions;
}) {
  const host = setup?.host;
  const bridge = setup?.bridge;
  const boards = setup?.boards ?? [];
  const sensors = setup?.sensors ?? [];
  const simulated = host?.sensor_source === "simulated";

  return (
    <div className="grid items-stretch gap-3 p-5 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1.6fr)]">
      <Node icon={<Laptop className="size-4" />} kind="Laptop" title={host?.hostname ?? "Not connected yet"}>
        {host ? (
          <>
            <Line>{host.os}</Line>
            <Line>
              builderwars {host.cli_version} · Python {host.python_version}
            </Line>
            <Line>Last started {timeAgo(setup?.reported_at)}</Line>
            {host.sensor_source && (
              <p className={`mt-2 text-xs ${simulated ? "text-warn" : "text-muted"}`}>
                {SOURCE_TEXT[host.sensor_source] ?? host.sensor_source}
              </p>
            )}
          </>
        ) : (
          <p className="text-xs text-muted">
            On the laptop the FREE-WILi is plugged into, run{" "}
            <code className="font-mono break-all text-fg-2">
              builderwars run --cloud --device-id {deviceId}
            </code>
          </p>
        )}
      </Node>

      <Link label="USB" />

      <Node
        icon={<Cpu className="size-4" />}
        kind="FREE-WILi"
        title={bridge ? (bridge.serial ? `Serial ${bridge.serial}` : bridge.model) : simulated ? "Not used" : "Not seen yet"}
        muted={!bridge}
      >
        {bridge ? (
          <>
            {bridge.main_port && <Line>Main CPU {bridge.main_port}</Line>}
            {bridge.display_port && <Line>Display CPU {bridge.display_port}</Line>}
            {bridge.library_version && <Line>freewili {bridge.library_version}</Line>}
          </>
        ) : (
          <p className="text-xs text-muted">
            {simulated
              ? "The last run was simulated, so no FREE-WILi was read."
              : "Shows up here once the CLI has opened it."}
          </p>
        )}
      </Node>

      <Link label="I2C · SPI · UART · GPIO" />

      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex items-center justify-between gap-2">
          <p className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted uppercase">
            <CircuitBoard className="size-3.5" aria-hidden="true" />
            Target boards · {boards.length} of {setup?.max_boards ?? 4}
          </p>
          {canEdit && boards.length < (setup?.max_boards ?? 4) && (
            <button className="btn-ghost px-2 py-1 text-xs" onClick={actions.addBoard}>
              <Plus className="size-3.5" aria-hidden="true" /> Add board
            </button>
          )}
        </div>
        {boards.length === 0 ? (
          <div className="rounded-lg border border-dashed border-line-strong px-4 py-5 text-center text-sm text-muted">
            {canEdit ? (
              <>
                No target boards yet.{" "}
                <button className="font-medium text-accent hover:underline" onClick={actions.addBoard}>
                  Add the board you're testing
                </button>{" "}
                and define its sensors.
              </>
            ) : (
              "No target boards yet. The project owner adds them."
            )}
          </div>
        ) : (
          boards.map((board) => (
            <BoardCard
              key={board.id}
              board={board}
              sensors={sensors.filter((s) => s.board_id === board.id)}
              latest={latest}
              canEdit={canEdit}
              actions={actions}
            />
          ))
        )}
      </div>
    </div>
  );
}

function BoardCard({
  board,
  sensors,
  latest,
  canEdit,
  actions,
}: {
  board: TargetBoard;
  sensors: Sensor[];
  latest: Record<string, TelemetryValue | undefined>;
  canEdit: boolean;
  actions: SetupActions;
}) {
  return (
    <div className="rounded-lg border border-line bg-surface-2/60">
      <div className="flex items-start justify-between gap-2 px-3.5 pt-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-fg">{board.name}</p>
          {board.notes && <p className="mt-0.5 line-clamp-2 text-xs text-muted">{board.notes}</p>}
        </div>
        {canEdit && (
          <IconButton label={`Edit or remove ${board.name}`} onClick={() => actions.editBoard(board)}>
            <Pencil className="size-3.5" />
          </IconButton>
        )}
      </div>
      <ul className="mt-2 divide-y divide-line border-t border-line">
        {sensors.map((s) => (
          <li key={s.id}>
            <SensorRow sensor={s} value={latest[s.key]} canEdit={canEdit} onEdit={() => actions.editSensor(s)} />
          </li>
        ))}
        {sensors.length === 0 && <li className="px-3.5 py-2.5 text-xs text-muted">No sensors on this board yet.</li>}
      </ul>
      {canEdit && (
        <div className="border-t border-line px-2 py-1.5">
          <button className="btn-ghost px-2 py-1 text-xs" onClick={() => actions.addSensor(board)}>
            <Plus className="size-3.5" aria-hidden="true" /> Add sensor
          </button>
        </div>
      )}
    </div>
  );
}

function SensorRow({
  sensor,
  value,
  canEdit,
  onEdit,
}: {
  sensor: Sensor;
  value: TelemetryValue | undefined;
  canEdit: boolean;
  onEdit: () => void;
}) {
  const body = (
    <>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="rounded bg-accent-soft px-1.5 py-0.5 font-mono text-[10px] font-semibold text-accent uppercase">
            {sensor.protocol}
          </span>
          <span className={`truncate text-sm ${sensor.enabled ? "text-fg" : "text-muted line-through"}`}>
            {sensor.name}
          </span>
        </span>
        <span className="mt-0.5 block truncate font-mono text-[11px] text-muted">
          {describeBus(sensor.bus)} · every {sensor.poll_interval_s}s
        </span>
      </span>
      <span className="shrink-0 text-sm font-medium tabular-nums text-fg-2">
        {sensor.enabled ? formatValue(value, sensor.unit ?? "") : "off"}
      </span>
    </>
  );
  return canEdit ? (
    <button
      className="flex w-full items-center gap-3 px-3.5 py-2 text-left hover:bg-surface"
      onClick={onEdit}
      title="Edit sensor"
    >
      {body}
    </button>
  ) : (
    <div className="flex items-center gap-3 px-3.5 py-2">{body}</div>
  );
}

function Node({
  icon,
  kind,
  title,
  muted = false,
  children,
}: {
  icon: ReactNode;
  kind: string;
  title: ReactNode;
  muted?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className={`min-w-0 self-start rounded-lg border border-line px-4 py-3.5 ${muted ? "bg-surface" : "bg-surface-2/60"}`}>
      <p className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted uppercase">
        <span aria-hidden="true">{icon}</span>
        {kind}
      </p>
      <p className={`mt-1.5 truncate text-sm font-semibold ${muted ? "text-muted" : "text-fg"}`}>{title}</p>
      <div className="mt-1 space-y-0.5">{children}</div>
    </div>
  );
}

function Line({ children }: { children: ReactNode }) {
  return <p className="truncate text-xs text-fg-2">{children}</p>;
}

/** The cable between two nodes: an arrow across on wide screens, down on narrow ones. */
function Link({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center gap-2 text-muted lg:flex-col lg:px-1" aria-hidden="true">
      <ArrowDown className="size-4 lg:hidden" />
      <ArrowRight className="hidden size-4 lg:block" />
      <span className="flex items-center gap-1 text-[10px] font-medium tracking-wide whitespace-nowrap uppercase lg:max-w-20 lg:text-center lg:whitespace-normal">
        {label === "USB" && <Usb className="size-3" />}
        {label}
      </span>
    </div>
  );
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button className="btn-ghost size-7 p-0" aria-label={label} title={label} onClick={onClick}>
      {children}
    </button>
  );
}
