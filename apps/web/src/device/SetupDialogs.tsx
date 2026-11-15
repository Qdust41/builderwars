import { BookOpen, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api } from "../api/client";
import type { Sensor, SensorPreset, SensorProtocol, TargetBoard } from "../api/types";
import { ErrorBanner, errorText, Spinner } from "../components/ui";
import { useAsync } from "../useAsync";
import {
  DATA_TYPES,
  decodePreview,
  DraftError,
  draftFrom,
  emptyDraft,
  parseBytes,
  PROTOCOLS,
  slugKey,
  toSensorInput,
  type SensorDraft,
} from "./sensors";

/** A centred dialog over a dimmed page; Escape or the backdrop closes it. */
function Modal({
  title,
  onClose,
  wide = false,
  children,
}: {
  title: string;
  onClose: () => void;
  wide?: boolean;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 px-4 py-8 sm:py-14"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`card w-full ${wide ? "max-w-3xl" : "max-w-lg"} shadow-xl`}
      >
        <div className="card-head">
          <h2 className="card-title">{title}</h2>
          <button className="btn-ghost size-8 p-0" aria-label="Close" onClick={onClose}>
            <X className="size-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  error,
  children,
  className = "",
}: {
  label: string;
  hint?: ReactNode;
  error?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`block min-w-0 ${className}`}>
      <span className={`field-label ${error ? "text-bad" : ""}`}>{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

/** Delete needs a second click within a few seconds. */
function DeleteButton({ label, onDelete, busy }: { label: string; onDelete: () => void; busy: boolean }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = window.setTimeout(() => setArmed(false), 4000);
    return () => window.clearTimeout(t);
  }, [armed]);
  return (
    <button
      type="button"
      className={`btn ${armed ? "bg-bad text-white hover:opacity-90" : "text-bad hover:bg-bad-soft"}`}
      disabled={busy}
      onClick={() => (armed ? onDelete() : setArmed(true))}
    >
      <Trash2 className="size-4" aria-hidden="true" />
      {armed ? "Click again to confirm" : label}
    </button>
  );
}

// -- target board -------------------------------------------------------------------------------

export function BoardDialog({
  deviceId,
  board,
  sensorCount,
  onClose,
  onSaved,
}: {
  deviceId: string;
  board?: TargetBoard;
  sensorCount: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(board?.name ?? "");
  const [notes, setNotes] = useState(board?.notes ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError(undefined);
    try {
      await work();
      onSaved();
      onClose();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body = { name: name.trim(), notes };
    void run(() => (board ? api.updateBoard(deviceId, board.id, body) : api.addBoard(deviceId, body)));
  };

  return (
    <Modal title={board ? "Edit target board" : "Add a target board"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4 p-5">
        <p className="text-sm text-muted">
          A board under test, wired to this device's FREE-WILi. One FREE-WILi drives up to 4.
        </p>
        <Field label="Name">
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Motor controller rev B"
            maxLength={120}
            required
            autoFocus
          />
        </Field>
        <Field label="Notes" hint="Optional: wiring, revision, what's being tested.">
          <textarea
            className="input min-h-20"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={2000}
            placeholder="TMP102 on I2C0, ADC on SPI1 CS0"
          />
        </Field>
        {error && <ErrorBanner>{error}</ErrorBanner>}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
          {board ? (
            <DeleteButton
              label={sensorCount ? `Remove board and its ${sensorCount} sensor(s)` : "Remove board"}
              busy={busy}
              onDelete={() => void run(() => api.deleteBoard(deviceId, board.id))}
            />
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button className="btn-primary" disabled={busy || !name.trim()}>
              {board ? "Save" : "Add board"}
            </button>
          </div>
        </div>
      </form>
    </Modal>
  );
}

// -- sensor -------------------------------------------------------------------------------------

export function SensorDialog({
  deviceId,
  boards,
  boardId,
  sensor,
  onClose,
  onSaved,
}: {
  deviceId: string;
  boards: TargetBoard[];
  boardId: string;
  sensor?: Sensor;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<SensorDraft>(() =>
    sensor ? draftFrom(sensor, sensor.board_id) : emptyDraft(boardId),
  );
  const [picking, setPicking] = useState(!sensor);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [badField, setBadField] = useState<string>();

  const set = <K extends keyof SensorDraft>(key: K, value: SensorDraft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));
  const setName = (name: string) =>
    setDraft((d) => ({ ...d, name, key: d.keyEdited ? d.key : slugKey(name) }));

  const usePreset = (preset: SensorPreset) => {
    setDraft({ ...draftFrom(preset.sensor, draft.boardId), keyEdited: true });
    setPicking(false);
  };

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError(undefined);
    try {
      await work();
      onSaved();
      onClose();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    let body;
    try {
      body = toSensorInput(draft);
    } catch (err) {
      if (err instanceof DraftError) {
        setBadField(err.field);
        setError(err.message);
        return;
      }
      throw err;
    }
    setBadField(undefined);
    void run(() => (sensor ? api.updateSensor(deviceId, sensor.id, body) : api.addSensor(deviceId, body)));
  };

  const bad = (field: string) => badField === field;
  const raw = draft.protocol === "i2c" || draft.protocol === "spi";

  return (
    <Modal title={sensor ? `Edit ${sensor.name}` : "Add a sensor"} onClose={onClose} wide>
      {picking ? (
        <PresetPicker onPick={usePreset} onSkip={() => setPicking(false)} />
      ) : (
        <form onSubmit={submit} className="space-y-6 p-5">
          {!sensor && (
            <button type="button" className="btn-secondary text-xs" onClick={() => setPicking(true)}>
              <BookOpen className="size-3.5" aria-hidden="true" /> Start from a common part
            </button>
          )}

          <fieldset className="grid gap-4 sm:grid-cols-2">
            <Field label="Name" error={bad("name")}>
              <input
                className="input"
                value={draft.name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Board temperature"
                maxLength={80}
                autoFocus
              />
            </Field>
            <Field
              label="Reading name"
              error={bad("key")}
              hint="How it appears in telemetry and CSVs. Unique on this device."
            >
              <input
                className="input font-mono"
                value={draft.key}
                onChange={(e) => setDraft((d) => ({ ...d, key: e.target.value, keyEdited: true }))}
                placeholder="board_temp_c"
                maxLength={64}
              />
            </Field>
            <Field label="Target board">
              <select className="input" value={draft.boardId} onChange={(e) => set("boardId", e.target.value)}>
                {boards.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Unit">
                <input
                  className="input"
                  value={draft.unit}
                  onChange={(e) => set("unit", e.target.value)}
                  placeholder="°C"
                  maxLength={16}
                />
              </Field>
              <Field label="Poll every (s)" error={bad("pollInterval")}>
                <input
                  className="input"
                  inputMode="decimal"
                  value={draft.pollInterval}
                  onChange={(e) => set("pollInterval", e.target.value)}
                />
              </Field>
            </div>
          </fieldset>

          <fieldset>
            <legend className="field-label">Protocol</legend>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" role="radiogroup">
              {PROTOCOLS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  role="radio"
                  aria-checked={draft.protocol === p.value}
                  onClick={() => set("protocol", p.value as SensorProtocol)}
                  className={`rounded-lg border px-3 py-2 text-left ${
                    draft.protocol === p.value
                      ? "border-accent bg-accent-soft"
                      : "border-line hover:bg-surface-2"
                  }`}
                >
                  <span className="block text-sm font-semibold text-fg">{p.label}</span>
                  <span className="block text-[11px] leading-snug text-muted">{p.hint}</span>
                </button>
              ))}
            </div>
          </fieldset>

          <BusFields draft={draft} set={set} bad={bad} />

          {draft.protocol !== "gpio" && (
            <fieldset className="space-y-4">
              <legend className="field-label">Turn the answer into a number</legend>
              <div className="grid gap-4 sm:grid-cols-3">
                {raw && (
                  <>
                    <Field label="Data type" className="sm:col-span-3">
                      <select
                        className="input"
                        value={draft.dataType}
                        onChange={(e) => set("dataType", e.target.value as SensorDraft["dataType"])}
                      >
                        {DATA_TYPES.map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Bit mask" error={bad("bitMask")} hint="Optional, e.g. 0x0FFF">
                      <input
                        className="input font-mono"
                        value={draft.bitMask}
                        onChange={(e) => set("bitMask", e.target.value)}
                      />
                    </Field>
                    <Field label="Shift right (bits)" error={bad("bitShift")}>
                      <input
                        className="input"
                        inputMode="numeric"
                        value={draft.bitShift}
                        onChange={(e) => set("bitShift", e.target.value)}
                      />
                    </Field>
                    <span className="hidden sm:block" />
                  </>
                )}
                <Field label="Multiply by" error={bad("scale")}>
                  <input
                    className="input"
                    inputMode="decimal"
                    value={draft.scale}
                    onChange={(e) => set("scale", e.target.value)}
                  />
                </Field>
                <Field label="Then add" error={bad("offset")}>
                  <input
                    className="input"
                    inputMode="decimal"
                    value={draft.offset}
                    onChange={(e) => set("offset", e.target.value)}
                  />
                </Field>
                <Field label="Round to (decimals)" error={bad("decimals")}>
                  <input
                    className="input"
                    inputMode="numeric"
                    value={draft.decimals}
                    onChange={(e) => set("decimals", e.target.value)}
                    placeholder="no rounding"
                  />
                </Field>
              </div>
              {raw && <DecodeTry draft={draft} set={set} />}
            </fieldset>
          )}

          <label className="flex items-center gap-2 text-sm text-fg-2">
            <input
              type="checkbox"
              className="size-4 accent-[var(--accent)]"
              checked={draft.enabled}
              onChange={(e) => set("enabled", e.target.checked)}
            />
            Read this sensor (untick to keep the definition but stop reading it)
          </label>

          {error && <ErrorBanner>{error}</ErrorBanner>}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-4">
            {sensor ? (
              <DeleteButton
                label="Remove sensor"
                busy={busy}
                onDelete={() => void run(() => api.deleteSensor(deviceId, sensor.id))}
              />
            ) : (
              <span className="text-xs text-muted">
                A running CLI picks up changes within 30 seconds.
              </span>
            )}
            <div className="flex gap-2">
              <button type="button" className="btn-secondary" onClick={onClose}>
                Cancel
              </button>
              <button className="btn-primary" disabled={busy}>
                {sensor ? "Save" : "Add sensor"}
              </button>
            </div>
          </div>
        </form>
      )}
    </Modal>
  );
}

type Setter = <K extends keyof SensorDraft>(key: K, value: SensorDraft[K]) => void;

function BusFields({ draft, set, bad }: { draft: SensorDraft; set: Setter; bad: (f: string) => boolean }) {
  if (draft.protocol === "i2c") {
    const writes = draft.setupWrites;
    const setWrite = (i: number, change: Partial<SensorDraft["setupWrites"][number]>) =>
      set(
        "setupWrites",
        writes.map((w, j) => (j === i ? { ...w, ...change } : w)),
      );
    return (
      <fieldset className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Chip address" error={bad("address")} hint="7-bit, e.g. 0x48">
            <input className="input font-mono" value={draft.address} onChange={(e) => set("address", e.target.value)} />
          </Field>
          <Field label="Register" error={bad("reg")}>
            <input className="input font-mono" value={draft.reg} onChange={(e) => set("reg", e.target.value)} />
          </Field>
          <Field label="Bytes to read" error={bad("length")}>
            <input
              className="input"
              inputMode="numeric"
              value={draft.length}
              onChange={(e) => set("length", e.target.value)}
            />
          </Field>
        </div>
        <div>
          <p className="field-label">Setup writes</p>
          <p className="mb-2 text-xs text-muted">
            Written before every read, in order: wake the chip, pick a channel, start a conversion.
          </p>
          <div className="space-y-2">
            {writes.map((w, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="w-8 shrink-0 text-xs text-muted">reg</span>
                <input
                  className={`input w-24 font-mono ${bad(`setup-${i}`) ? "border-bad" : ""}`}
                  value={w.reg}
                  onChange={(e) => setWrite(i, { reg: e.target.value })}
                  aria-label={`Setup write ${i + 1} register`}
                />
                <span className="shrink-0 text-xs text-muted">bytes</span>
                <input
                  className={`input font-mono ${bad(`setup-${i}`) ? "border-bad" : ""}`}
                  value={w.data}
                  onChange={(e) => setWrite(i, { data: e.target.value })}
                  placeholder="C2 83"
                  aria-label={`Setup write ${i + 1} bytes`}
                />
                <button
                  type="button"
                  className="btn-ghost size-9 shrink-0 p-0"
                  aria-label={`Remove setup write ${i + 1}`}
                  onClick={() => set("setupWrites", writes.filter((_, j) => j !== i))}
                >
                  <X className="size-4" />
                </button>
              </div>
            ))}
          </div>
          {writes.length < 8 && (
            <button
              type="button"
              className="btn-ghost mt-1 px-2 py-1 text-xs"
              onClick={() => set("setupWrites", [...writes, { reg: "0x01", data: "" }])}
            >
              <Plus className="size-3.5" aria-hidden="true" /> Add setup write
            </button>
          )}
        </div>
      </fieldset>
    );
  }
  if (draft.protocol === "spi") {
    return (
      <fieldset className="grid gap-4 sm:grid-cols-3">
        <Field label="Bytes to send" error={bad("write")} hint="Hex. Pad with 00 to clock the reply in." className="sm:col-span-3">
          <input className="input font-mono" value={draft.write} onChange={(e) => set("write", e.target.value)} />
        </Field>
        <Field label="Keep from byte" error={bad("readOffset")} hint="0 = first byte back">
          <input
            className="input"
            inputMode="numeric"
            value={draft.readOffset}
            onChange={(e) => set("readOffset", e.target.value)}
          />
        </Field>
        <Field label="Bytes to keep" error={bad("spiLength")}>
          <input
            className="input"
            inputMode="numeric"
            value={draft.spiLength}
            onChange={(e) => set("spiLength", e.target.value)}
          />
        </Field>
        <Field label="Mode" hint="Set on the FREE-WILi; noted here">
          <select className="input" value={draft.mode} onChange={(e) => set("mode", e.target.value)}>
            {[0, 1, 2, 3].map((m) => (
              <option key={m} value={m}>
                Mode {m}
              </option>
            ))}
          </select>
        </Field>
      </fieldset>
    );
  }
  if (draft.protocol === "uart") {
    return (
      <fieldset className="grid gap-4 sm:grid-cols-3">
        <Field label="Command to send" hint="Empty: just listen" className="sm:col-span-2">
          <input
            className="input font-mono"
            value={draft.command}
            onChange={(e) => set("command", e.target.value)}
            placeholder="READ?"
            maxLength={64}
          />
        </Field>
        <Field label="Line ending">
          <select
            className="input"
            value={JSON.stringify(draft.lineEnding)}
            onChange={(e) => set("lineEnding", JSON.parse(e.target.value) as SensorDraft["lineEnding"])}
          >
            <option value={JSON.stringify("\n")}>LF (\n)</option>
            <option value={JSON.stringify("\r\n")}>CRLF (\r\n)</option>
            <option value={JSON.stringify("\r")}>CR (\r)</option>
            <option value={JSON.stringify("")}>None</option>
          </select>
        </Field>
        <Field
          label="Find the value with"
          hint="Optional regex; its group (or the whole match) is the number. Default: the first number."
          className="sm:col-span-3"
        >
          <input
            className="input font-mono"
            value={draft.pattern}
            onChange={(e) => set("pattern", e.target.value)}
            placeholder="T=([-0-9.]+)"
          />
        </Field>
        <Field label="Wait for reply (s)" error={bad("timeout")}>
          <input
            className="input"
            inputMode="decimal"
            value={draft.timeout}
            onChange={(e) => set("timeout", e.target.value)}
          />
        </Field>
        <Field label="Baud rate" error={bad("baud")} hint="Set on the FREE-WILi; noted here">
          <input
            className="input"
            inputMode="numeric"
            value={draft.baud}
            onChange={(e) => set("baud", e.target.value)}
            placeholder="115200"
          />
        </Field>
      </fieldset>
    );
  }
  return (
    <fieldset className="grid gap-4 sm:grid-cols-3">
      <Field label="FREE-WILi GPIO" error={bad("pin")} hint="e.g. 26 (the header's input pin)">
        <input className="input" inputMode="numeric" value={draft.pin} onChange={(e) => set("pin", e.target.value)} />
      </Field>
      <p className="self-center text-sm text-muted sm:col-span-2">Reads 1 when the pin is high, 0 when low.</p>
    </fieldset>
  );
}

/** Type the bytes a sensor would answer and see the value this definition makes of them. */
function DecodeTry({ draft, set }: { draft: SensorDraft; set: Setter }) {
  let result: string;
  let ok = false;
  try {
    const decode = toSensorInput({ ...draft, name: draft.name || "x", key: draft.key || "x" }).decode;
    const bytes = parseBytes(draft.sampleBytes);
    if (!draft.sampleBytes.trim()) result = "type example bytes to check the maths";
    else if (!bytes) result = "enter hex bytes, e.g. 19 00";
    else {
      result = `= ${decodePreview(bytes, decode!)}${draft.unit ? ` ${draft.unit}` : ""}`;
      ok = true;
    }
  } catch (err) {
    result = err instanceof Error ? err.message : String(err);
  }
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg bg-surface-2 px-3.5 py-2.5 text-sm">
      <span className="text-muted">Try it: bytes</span>
      <input
        className="input w-36 py-1 font-mono"
        value={draft.sampleBytes}
        onChange={(e) => set("sampleBytes", e.target.value)}
        placeholder="19 00"
        aria-label="Example bytes"
      />
      <span className={ok ? "font-semibold tabular-nums text-fg" : "text-xs text-muted"}>{result}</span>
    </div>
  );
}

/** The table of common parts (from the API), filterable. */
function PresetPicker({ onPick, onSkip }: { onPick: (p: SensorPreset) => void; onSkip: () => void }) {
  const presets = useAsync(() => api.listSensorPresets(), []);
  const [query, setQuery] = useState("");
  const [protocol, setProtocol] = useState<SensorProtocol | "all">("all");
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => searchRef.current?.focus(), []);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (presets.data ?? []).filter(
      (p) =>
        (protocol === "all" || p.sensor.bus.protocol === protocol) &&
        (!q || `${p.part} ${p.manufacturer} ${p.measures}`.toLowerCase().includes(q)),
    );
  }, [presets.data, query, protocol]);

  return (
    <div>
      <div className="flex flex-col gap-3 border-b border-line p-5 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-muted" aria-hidden="true" />
          <input
            ref={searchRef}
            className="input pl-9"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search parts: TMP102, current, accelerometer…"
            aria-label="Search common parts"
          />
        </div>
        <select
          className="input sm:w-36"
          value={protocol}
          onChange={(e) => setProtocol(e.target.value as SensorProtocol | "all")}
          aria-label="Protocol"
        >
          <option value="all">All protocols</option>
          {PROTOCOLS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </div>
      {presets.loading ? (
        <Spinner label="Loading common parts…" />
      ) : presets.error ? (
        <div className="p-5">
          <ErrorBanner>{errorText(presets.error)}</ErrorBanner>
        </div>
      ) : (
        <div className="max-h-[26rem] overflow-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-surface-2 text-xs text-muted">
              <tr>
                <th className="px-5 py-2 font-medium">Part</th>
                <th className="px-3 py-2 font-medium">Measures</th>
                <th className="hidden px-3 py-2 font-medium sm:table-cell">Bus</th>
                <th className="hidden px-3 py-2 font-medium md:table-cell">Notes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((p) => (
                <tr
                  key={p.id}
                  className="cursor-pointer align-top hover:bg-accent-soft/60"
                  onClick={() => onPick(p)}
                  onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onPick(p)}
                  tabIndex={0}
                >
                  <td className="px-5 py-2.5">
                    <span className="font-medium text-fg">{p.part}</span>
                    <span className="block text-xs text-muted">{p.manufacturer}</span>
                  </td>
                  <td className="px-3 py-2.5 text-fg-2">
                    {p.measures}
                    {p.sensor.unit && <span className="text-muted"> ({p.sensor.unit})</span>}
                  </td>
                  <td className="hidden px-3 py-2.5 sm:table-cell">
                    <span className="rounded bg-accent-soft px-1.5 py-0.5 font-mono text-[10px] font-semibold text-accent uppercase">
                      {p.sensor.bus.protocol}
                    </span>
                  </td>
                  <td className="hidden max-w-xs px-3 py-2.5 text-xs text-muted md:table-cell">
                    {p.notes}
                    {p.datasheet && (
                      <>
                        {" "}
                        <a
                          href={p.datasheet}
                          target="_blank"
                          rel="noreferrer"
                          className="text-accent hover:underline"
                          onClick={(e) => e.stopPropagation()}
                        >
                          Datasheet
                        </a>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-5 py-6 text-center text-muted">
                    No common part matches. Define it yourself instead.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-3.5">
        <span className="text-xs text-muted">Every field stays editable after you pick a part.</span>
        <button type="button" className="btn-secondary" onClick={onSkip}>
          Define it myself
        </button>
      </div>
    </div>
  );
}
