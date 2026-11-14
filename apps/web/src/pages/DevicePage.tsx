import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { DeviceCommand } from "../api/types";
import { useAsync } from "../useAsync";

export function DevicePage() {
  const { deviceId = "" } = useParams();
  const device = useAsync(() => api.getDevice(deviceId), [deviceId]);
  const [command, setCommand] = useState<DeviceCommand>();
  const [commandError, setCommandError] = useState<string>();

  async function ping() {
    if (!device.data) return;
    setCommandError(undefined);
    try {
      setCommand(await api.sendCommand(device.data.project_id, device.data.id, "ping"));
    } catch (err) {
      setCommandError(String(err));
    }
  }

  async function refreshCommand() {
    if (command) setCommand(await api.getCommand(command.id));
  }

  if (device.error) return <p className="error">{device.error}</p>;
  const d = device.data;
  return (
    <section>
      <h1>{d?.display_name ?? "…"}</h1>
      <dl>
        <dt>Status</dt>
        <dd>{d?.connection_status}</dd>
        <dt>Hardware</dt>
        <dd>
          {d?.hardware_model}
          {d?.extensions.length ? ` + ${d.extensions.join(", ")}` : ""}
        </dd>
        <dt>Firmware</dt>
        <dd>{d?.firmware_version ?? "unknown"}</dd>
        <dt>Last seen</dt>
        <dd>{d?.last_seen_at ?? "never"}</dd>
      </dl>
      <h2>Commands</h2>
      <button onClick={ping}>Send ping</button>
      {command && (
        <p>
          <code>{command.name}</code>: {command.status}{" "}
          <button onClick={refreshCommand}>Refresh</button>
        </p>
      )}
      {commandError && <p className="error">{commandError}</p>}
      <p className="todo">
        TODO: telemetry chart, log stream, live command results via the session channel.
      </p>
    </section>
  );
}
