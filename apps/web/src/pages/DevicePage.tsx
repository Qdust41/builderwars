import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { useAsync } from "../useAsync";

export function DevicePage() {
  const { deviceId = "" } = useParams();
  const device = useAsync(() => api.getDevice(deviceId), [deviceId]);
  if (device.error) return <p className="error">{device.error}</p>;
  const d = device.data;
  return (
    <section>
      <h1>{d?.display_name ?? "…"}</h1>
      <dl>
        <dt>Status</dt>
        <dd>{d?.connection_status}</dd>
        <dt>Hardware</dt>
        <dd>{d?.hardware_model}</dd>
        <dt>Firmware</dt>
        <dd>{d?.firmware_version ?? "unknown"}</dd>
        <dt>Last seen</dt>
        <dd>{d?.last_seen_at ?? "never"}</dd>
      </dl>
      <p className="todo">TODO: telemetry chart, log stream, command panel (server-authorised).</p>
    </section>
  );
}
