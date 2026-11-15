// Sensor definitions on the device page: the form's text fields <-> the API's SensorInput,
// a client-side decode preview (mirrors device_protocol.sensors), and short descriptions.
import type {
  Sensor,
  SensorBus,
  SensorDataType,
  SensorDecode,
  SensorInput,
  SensorProtocol,
} from "../api/types";

export const PROTOCOLS: { value: SensorProtocol; label: string; hint: string }[] = [
  { value: "i2c", label: "I2C", hint: "Read a register (SDA GPIO16, SCL GPIO17)" },
  { value: "spi", label: "SPI", hint: "Send bytes, keep part of the reply (CS GPIO13)" },
  { value: "uart", label: "UART", hint: "Send a command, read a number back (UART1)" },
  { value: "gpio", label: "GPIO", hint: "High/low level of one pin" },
];

export const DATA_TYPES: { value: SensorDataType; label: string; size: number }[] = [
  { value: "u8", label: "unsigned 8-bit", size: 1 },
  { value: "i8", label: "signed 8-bit", size: 1 },
  { value: "u16_be", label: "unsigned 16-bit, big endian", size: 2 },
  { value: "u16_le", label: "unsigned 16-bit, little endian", size: 2 },
  { value: "i16_be", label: "signed 16-bit, big endian", size: 2 },
  { value: "i16_le", label: "signed 16-bit, little endian", size: 2 },
  { value: "u32_be", label: "unsigned 32-bit, big endian", size: 4 },
  { value: "u32_le", label: "unsigned 32-bit, little endian", size: 4 },
  { value: "i32_be", label: "signed 32-bit, big endian", size: 4 },
  { value: "i32_le", label: "signed 32-bit, little endian", size: 4 },
  { value: "f32_be", label: "float 32-bit, big endian", size: 4 },
  { value: "f32_le", label: "float 32-bit, little endian", size: 4 },
];

export const sizeOf = (t: SensorDataType) => DATA_TYPES.find((d) => d.value === t)?.size ?? 1;

/** "0x48", "48h", "72" -> 72. Bare digits are decimal; undefined when unreadable. */
export function parseNumber(text: string): number | undefined {
  const t = text.trim().toLowerCase();
  if (!t) return undefined;
  if (/^0x[0-9a-f]+$/.test(t)) return parseInt(t.slice(2), 16);
  if (/^[0-9a-f]+h$/.test(t)) return parseInt(t.slice(0, -1), 16);
  if (/^-?\d+$/.test(t)) return parseInt(t, 10);
  return undefined;
}

/** "C2 83", "0xC2,0x83", "c283" -> [0xC2, 0x83]. Always hex. */
export function parseBytes(text: string): number[] | undefined {
  const cleaned = text.trim();
  if (!cleaned) return [];
  const parts = /[\s,]/.test(cleaned)
    ? cleaned.split(/[\s,]+/).filter(Boolean)
    : (cleaned.replace(/^0x/i, "").match(/.{1,2}/g) ?? []);
  const out: number[] = [];
  for (const part of parts) {
    const p = part.replace(/^0x/i, "");
    if (!/^[0-9a-fA-F]{1,2}$/.test(p)) return undefined;
    out.push(parseInt(p, 16));
  }
  return out;
}

export const hex = (n: number, width = 2) => `0x${n.toString(16).toUpperCase().padStart(width, "0")}`;
export const hexBytes = (bytes: number[]) =>
  bytes.map((b) => b.toString(16).toUpperCase().padStart(2, "0")).join(" ");

/** "Board temperature" -> "board_temperature" (the telemetry reading name). */
export function slugKey(name: string): string {
  const s = name
    .normalize("NFKD")
    .replace(/[^\w\s-]/g, "")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^[^a-z]+/, "");
  return s.slice(0, 64);
}

/** Mirrors device_protocol.sensors.decode_bytes, for the form's "try it" preview. */
export function decodePreview(raw: number[], decode: SensorDecode): number {
  const size = sizeOf(decode.data_type);
  if (raw.length < size) throw new Error(`needs ${size} byte(s), got ${raw.length}`);
  const view = new DataView(new Uint8Array(raw.slice(0, size)).buffer);
  const little = decode.data_type.endsWith("_le");
  let value: number;
  switch (decode.data_type) {
    case "u8":
      value = view.getUint8(0);
      break;
    case "i8":
      value = view.getInt8(0);
      break;
    case "u16_be":
    case "u16_le":
      value = view.getUint16(0, little);
      break;
    case "i16_be":
    case "i16_le":
      value = view.getInt16(0, little);
      break;
    case "u32_be":
    case "u32_le":
      value = view.getUint32(0, little);
      break;
    case "i32_be":
    case "i32_le":
      value = view.getInt32(0, little);
      break;
    default:
      value = view.getFloat32(0, little);
  }
  if (!decode.data_type.startsWith("f")) {
    let big = BigInt(value);
    if (decode.bit_mask != null) big &= BigInt(decode.bit_mask);
    big >>= BigInt(decode.bit_shift ?? 0);
    value = Number(big);
  }
  return applyScale(value, decode);
}

export function applyScale(value: number, decode: SensorDecode): number {
  const scale = decode.scale ?? 1;
  const offset = decode.offset ?? 0;
  let out = value * scale + offset;
  if (decode.decimals != null) out = Number(out.toFixed(decode.decimals));
  return out;
}

/** One line saying where a sensor is read, e.g. "I2C 0x48 · reg 0x00 · 2 bytes". */
export function describeBus(bus: SensorBus): string {
  switch (bus.protocol) {
    case "i2c": {
      const setup = bus.setup_writes?.length ? ` · ${bus.setup_writes.length} setup write(s)` : "";
      return `I2C ${hex(bus.address)} · reg ${hex(bus.reg)} · ${bus.length} byte${bus.length === 1 ? "" : "s"}${setup}`;
    }
    case "spi":
      return `SPI send ${hexBytes(bus.write)} · keep ${bus.length} from byte ${bus.read_offset}`;
    case "uart":
      return bus.command ? `UART “${bus.command}”` : "UART (listen)";
    default:
      return `GPIO${bus.pin}`;
  }
}

// -- the form ---------------------------------------------------------------------------------

export interface SetupWriteDraft {
  reg: string;
  data: string;
}

/** Everything the sensor form edits, as the text the person typed. */
export interface SensorDraft {
  boardId: string;
  name: string;
  key: string;
  keyEdited: boolean;
  unit: string;
  pollInterval: string;
  enabled: boolean;
  protocol: SensorProtocol;
  // I2C
  address: string;
  reg: string;
  length: string;
  setupWrites: SetupWriteDraft[];
  // SPI
  write: string;
  readOffset: string;
  spiLength: string;
  mode: string;
  clockHz: string;
  // UART
  command: string;
  lineEnding: "" | "\n" | "\r\n" | "\r";
  pattern: string;
  timeout: string;
  baud: string;
  // GPIO
  pin: string;
  // decode
  dataType: SensorDataType;
  bitMask: string;
  bitShift: string;
  scale: string;
  offset: string;
  decimals: string;
  sampleBytes: string;
}

export function emptyDraft(boardId: string): SensorDraft {
  return {
    boardId,
    name: "",
    key: "",
    keyEdited: false,
    unit: "",
    pollInterval: "1",
    enabled: true,
    protocol: "i2c",
    address: "0x48",
    reg: "0x00",
    length: "2",
    setupWrites: [],
    write: "00 00",
    readOffset: "0",
    spiLength: "2",
    mode: "0",
    clockHz: "",
    command: "",
    lineEnding: "\n",
    pattern: "",
    timeout: "0.5",
    baud: "",
    pin: "26",
    dataType: "u16_be",
    bitMask: "",
    bitShift: "0",
    scale: "1",
    offset: "0",
    decimals: "",
    sampleBytes: "",
  };
}

type SpecLike = Pick<Sensor, "key" | "name" | "unit" | "poll_interval_s" | "enabled" | "bus"> & {
  decode?: SensorDecode;
};

/** A stored sensor or a preset, as form fields. */
export function draftFrom(spec: SpecLike, boardId: string): SensorDraft {
  const d = emptyDraft(boardId);
  const decode = spec.decode;
  const draft: SensorDraft = {
    ...d,
    name: spec.name,
    key: spec.key,
    keyEdited: true,
    unit: spec.unit ?? "",
    pollInterval: String(spec.poll_interval_s ?? 1),
    enabled: spec.enabled ?? true,
    protocol: spec.bus.protocol,
    dataType: decode?.data_type ?? "u8",
    bitMask: decode?.bit_mask != null ? hex(decode.bit_mask, 2) : "",
    bitShift: String(decode?.bit_shift ?? 0),
    scale: String(decode?.scale ?? 1),
    offset: String(decode?.offset ?? 0),
    decimals: decode?.decimals != null ? String(decode.decimals) : "",
  };
  const bus = spec.bus;
  if (bus.protocol === "i2c") {
    Object.assign(draft, {
      address: hex(bus.address),
      reg: hex(bus.reg),
      length: String(bus.length),
      setupWrites: (bus.setup_writes ?? []).map((w) => ({ reg: hex(w.reg), data: hexBytes(w.data) })),
    });
  } else if (bus.protocol === "spi") {
    Object.assign(draft, {
      write: hexBytes(bus.write),
      readOffset: String(bus.read_offset ?? 1),
      spiLength: String(bus.length ?? 1),
      mode: String(bus.mode ?? 0),
      clockHz: bus.clock_hz != null ? String(bus.clock_hz) : "",
    });
  } else if (bus.protocol === "uart") {
    Object.assign(draft, {
      command: bus.command ?? "",
      lineEnding: bus.line_ending ?? "\n",
      pattern: bus.response_pattern ?? "",
      timeout: String(bus.timeout_s ?? 0.5),
      baud: bus.baud != null ? String(bus.baud) : "",
    });
  } else {
    draft.pin = String(bus.pin);
  }
  return draft;
}

export class DraftError extends Error {
  constructor(
    readonly field: keyof SensorDraft | string,
    message: string,
  ) {
    super(message);
  }
}

function num(text: string, field: string, label: string): number {
  const n = parseNumber(text);
  if (n === undefined) throw new DraftError(field, `${label}: enter a number (0x.. for hex)`);
  return n;
}

function float(text: string, field: string, label: string): number {
  const n = Number(text.trim());
  if (!text.trim() || !Number.isFinite(n)) throw new DraftError(field, `${label}: enter a number`);
  return n;
}

function optionalInt(text: string, field: string, label: string): number | null {
  return text.trim() ? num(text, field, label) : null;
}

/** Form fields -> the API body. Throws DraftError naming the field that is wrong. */
export function toSensorInput(d: SensorDraft): SensorInput {
  if (!d.name.trim()) throw new DraftError("name", "Give the sensor a name");
  const key = d.key.trim();
  if (!/^[a-z][a-z0-9_]{0,63}$/.test(key))
    throw new DraftError("key", "Reading name: lowercase letters, digits and _, starting with a letter");
  let bus: SensorBus;
  if (d.protocol === "i2c") {
    bus = {
      protocol: "i2c",
      address: num(d.address, "address", "Address"),
      reg: num(d.reg, "reg", "Register"),
      length: num(d.length, "length", "Bytes to read"),
      setup_writes: d.setupWrites.map((w, i) => {
        const data = parseBytes(w.data);
        if (!data?.length) throw new DraftError(`setup-${i}`, `Setup write ${i + 1}: enter hex bytes, e.g. C2 83`);
        return { reg: num(w.reg, `setup-${i}`, `Setup write ${i + 1} register`), data };
      }),
    };
  } else if (d.protocol === "spi") {
    const write = parseBytes(d.write);
    if (!write?.length) throw new DraftError("write", "Bytes to send: enter hex bytes, e.g. 01 80 00");
    bus = {
      protocol: "spi",
      write,
      read_offset: num(d.readOffset, "readOffset", "Keep from byte"),
      length: num(d.spiLength, "spiLength", "Bytes to keep"),
      mode: Number(d.mode) as 0 | 1 | 2 | 3,
      clock_hz: optionalInt(d.clockHz, "clockHz", "Clock"),
    };
  } else if (d.protocol === "uart") {
    bus = {
      protocol: "uart",
      command: d.command,
      line_ending: d.lineEnding,
      response_pattern: d.pattern.trim() || null,
      timeout_s: float(d.timeout, "timeout", "Timeout"),
      baud: optionalInt(d.baud, "baud", "Baud rate"),
    };
  } else {
    bus = { protocol: "gpio", pin: num(d.pin, "pin", "Pin") };
  }
  const decode: SensorDecode = {
    data_type: d.protocol === "i2c" || d.protocol === "spi" ? d.dataType : "u8",
    bit_mask: d.protocol === "i2c" || d.protocol === "spi" ? optionalInt(d.bitMask, "bitMask", "Bit mask") : null,
    bit_shift: d.protocol === "i2c" || d.protocol === "spi" ? num(d.bitShift || "0", "bitShift", "Shift") : 0,
    scale: float(d.scale || "1", "scale", "Scale"),
    offset: float(d.offset || "0", "offset", "Offset"),
    decimals: optionalInt(d.decimals, "decimals", "Decimals"),
  };
  return {
    board_id: d.boardId,
    key,
    name: d.name.trim(),
    unit: d.unit.trim() || null,
    poll_interval_s: float(d.pollInterval, "pollInterval", "Poll every"),
    enabled: d.enabled,
    bus,
    decode,
  };
}
