import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { realtime as defaultRealtime } from "../realtime";
import { MAX_LOG_ENTRIES, MAX_SAMPLES, mergeLogs, mergeSamples } from "./telemetry";
const MAX_COMMANDS = 20;
function statusRank(status) {
    return status === "queued" ? 0 : status === "sent" ? 1 : 2;
}
/**
 * Loads a device's recent telemetry, logs and commands, then keeps them current from the
 * device's realtime channel. Events are hints: every (re)subscribe refetches from the API.
 */
export function useDeviceLive(deviceId, client = api, realtime = defaultRealtime) {
    const [device, setDevice] = useState();
    const [error, setError] = useState();
    const [samples, setSamples] = useState([]);
    const [logs, setLogs] = useState([]);
    const [commands, setCommands] = useState([]);
    const [live, setLive] = useState("connecting");
    const [liveError, setLiveError] = useState();
    const [commandError, setCommandError] = useState();
    const deviceRef = useRef(undefined);
    const upsertCommand = useCallback((command) => {
        setCommands((list) => {
            const existing = list.find((c) => c.id === command.id);
            // Responses can arrive out of order; never move a command back to an earlier status.
            if (existing && statusRank(existing.status) > statusRank(command.status))
                return list;
            return [command, ...list.filter((c) => c.id !== command.id)]
                .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
                .slice(0, MAX_COMMANDS);
        });
    }, []);
    useEffect(() => {
        let cancelled = false;
        let unsubscribe;
        setDevice(undefined);
        setError(undefined);
        setSamples([]);
        setLogs([]);
        setCommands([]);
        setLive("connecting");
        const refresh = async () => {
            const [d, t, l] = await Promise.all([
                client.getDevice(deviceId),
                client.getTelemetry(deviceId, MAX_SAMPLES),
                client.getLogs(deviceId, MAX_LOG_ENTRIES),
            ]);
            if (cancelled)
                return;
            deviceRef.current = d;
            setDevice(d);
            setSamples((cur) => mergeSamples(cur, t));
            setLogs((cur) => mergeLogs(cur, l));
        };
        const onEvent = (event) => {
            if (event.device_id !== deviceId)
                return;
            switch (event.type) {
                case "device.telemetry": {
                    const data = event.data;
                    if (!Array.isArray(data.samples))
                        return;
                    setSamples((cur) => mergeSamples(cur, data.samples));
                    markSeen(data.samples.at(-1)?.ts);
                    return;
                }
                case "device.log": {
                    const data = event.data;
                    setLogs((cur) => mergeLogs(cur, [data]));
                    markSeen(data.at);
                    return;
                }
                case "device.status_changed": {
                    // The CLI started or stopped (or the API noticed it had gone silent).
                    const data = event.data;
                    const d = deviceRef.current;
                    if (!d || !data.connection_status)
                        return;
                    const next = {
                        ...d,
                        connection_status: data.connection_status,
                        last_seen_at: data.last_seen_at ?? d.last_seen_at,
                    };
                    deviceRef.current = next;
                    setDevice(next);
                    return;
                }
                case "device.command.updated": {
                    const data = event.data;
                    // The event is a hint; the API record is the truth (and covers commands sent by
                    // other people viewing this device).
                    client.getCommand(data.command_id).then((c) => !cancelled && upsertCommand(c), () => undefined);
                    return;
                }
                default:
                    return;
            }
        };
        const markSeen = (at) => {
            const d = deviceRef.current;
            if (!at || !d)
                return;
            if (d.last_seen_at && Date.parse(d.last_seen_at) >= Date.parse(at))
                return;
            const next = { ...d, last_seen_at: at, connection_status: "online" };
            deviceRef.current = next;
            setDevice(next);
        };
        (async () => {
            try {
                await refresh();
                const channel = await client.getDeviceChannel(deviceId);
                if (cancelled)
                    return;
                const off = await realtime.subscribe(channel.channel, onEvent, {
                    onReady: () => {
                        setLive("live");
                        setLiveError(undefined);
                        refresh().catch(() => undefined);
                    },
                    onError: (err) => {
                        setLive("reconnecting");
                        setLiveError(err.message);
                    },
                });
                if (cancelled)
                    off();
                else
                    unsubscribe = off;
            }
            catch (err) {
                if (cancelled)
                    return;
                if (deviceRef.current) {
                    setLive("offline");
                    setLiveError(String(err));
                }
                else {
                    setError(String(err));
                }
            }
        })();
        return () => {
            cancelled = true;
            unsubscribe?.();
        };
    }, [deviceId, client, realtime, upsertCommand]);
    // Nothing announces a command that expires unanswered (board offline), so look again just
    // after it expires; the API times it out on read.
    useEffect(() => {
        const timers = commands
            .filter((c) => (c.status === "queued" || c.status === "sent") && c.expires_at)
            .map((c) => window.setTimeout(() => client.getCommand(c.id).then(upsertCommand, () => undefined), Math.max(0, Date.parse(c.expires_at) - Date.now()) + 1500));
        return () => timers.forEach((t) => window.clearTimeout(t));
    }, [commands, client, upsertCommand]);
    const sendCommand = useCallback(async (name, args = {}) => {
        const d = deviceRef.current;
        if (!d)
            return;
        setCommandError(undefined);
        try {
            upsertCommand(await client.sendCommand(d.project_id, d.id, name, args));
        }
        catch (err) {
            setCommandError(String(err));
        }
    }, [client, upsertCommand]);
    return { device, error, samples, logs, commands, live, liveError, sendCommand, commandError };
}
