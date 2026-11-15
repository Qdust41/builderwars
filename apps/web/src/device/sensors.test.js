import { describe, expect, it } from "vitest";
import { decodePreview, DraftError, draftFrom, emptyDraft, parseBytes, parseNumber, slugKey, toSensorInput, } from "./sensors";
describe("number and byte parsing", () => {
    it("reads hex and decimal", () => {
        expect(parseNumber("0x48")).toBe(72);
        expect(parseNumber("48h")).toBe(72);
        expect(parseNumber("72")).toBe(72);
        expect(parseNumber("zz")).toBeUndefined();
    });
    it("reads byte lists in several spellings", () => {
        expect(parseBytes("C2 83")).toEqual([0xc2, 0x83]);
        expect(parseBytes("0xC2,0x83")).toEqual([0xc2, 0x83]);
        expect(parseBytes("c283")).toEqual([0xc2, 0x83]);
        expect(parseBytes("C2 3G")).toBeUndefined();
    });
    it("turns a name into a reading name", () => {
        expect(slugKey("Board temperature (°C)")).toBe("board_temperature_c");
        expect(slugKey("2nd ADC")).toBe("nd_adc");
    });
});
describe("decode preview matches the CLI", () => {
    it("TMP102: signed 16-bit, shift 4, 0.0625 per bit", () => {
        const decode = { data_type: "i16_be", bit_shift: 4, scale: 0.0625, offset: 0 };
        expect(decodePreview([0x19, 0x00], decode)).toBe(25);
        expect(decodePreview([0xe7, 0x00], decode)).toBe(-25);
    });
    it("masks before shifting and rounds", () => {
        const decode = {
            data_type: "u16_be",
            bit_mask: 0x7ff8,
            bit_shift: 3,
            scale: 0.25,
            offset: 0,
            decimals: 1,
        };
        expect(decodePreview([0x0c, 0x80], decode)).toBe(100);
    });
    it("complains about short answers", () => {
        expect(() => decodePreview([1], { data_type: "u16_le", bit_shift: 0, scale: 1, offset: 0 })).toThrow(/2 byte/);
    });
});
describe("form <-> API body", () => {
    it("round-trips an I2C sensor with setup writes", () => {
        const sensor = {
            key: "ads_v",
            name: "ADS1115",
            unit: "V",
            poll_interval_s: 2,
            enabled: true,
            bus: {
                protocol: "i2c",
                address: 0x48,
                reg: 0,
                length: 2,
                setup_writes: [{ reg: 1, data: [0xc2, 0x83] }],
            },
            decode: { data_type: "i16_be", bit_shift: 0, scale: 0.000125, offset: 0 },
        };
        const body = toSensorInput(draftFrom(sensor, "brd_1"));
        expect(body.board_id).toBe("brd_1");
        expect(body.bus).toEqual(sensor.bus);
        expect(body.decode).toMatchObject({ data_type: "i16_be", scale: 0.000125 });
    });
    it("names the bad field", () => {
        const draft = { ...emptyDraft("brd_1"), name: "T", key: "t", address: "nope" };
        expect(() => toSensorInput(draft)).toThrow(DraftError);
        try {
            toSensorInput(draft);
        }
        catch (err) {
            expect(err.field).toBe("address");
        }
    });
    it("builds GPIO and UART buses", () => {
        const gpio = toSensorInput({ ...emptyDraft("b"), name: "Btn", key: "btn", protocol: "gpio", pin: "26" });
        expect(gpio.bus).toEqual({ protocol: "gpio", pin: 26 });
        const uart = toSensorInput({
            ...emptyDraft("b"),
            name: "U",
            key: "u",
            protocol: "uart",
            command: "READ?",
            baud: "115200",
        });
        expect(uart.bus).toMatchObject({ protocol: "uart", command: "READ?", baud: 115200, response_pattern: null });
    });
});
describe("board status", () => {
    it("is online only while the board has been heard from recently", async () => {
        const { effectiveStatus, STALE_AFTER_MS } = await import("./telemetry");
        const now = Date.parse("2026-11-15T10:00:00Z");
        const seen = (msAgo) => new Date(now - msAgo).toISOString();
        expect(effectiveStatus({ connection_status: "online", last_seen_at: seen(5_000) }, now)).toBe("online");
        expect(effectiveStatus({ connection_status: "online", last_seen_at: seen(STALE_AFTER_MS + 1) }, now)).toBe("offline");
        expect(effectiveStatus({ connection_status: "offline", last_seen_at: seen(1) }, now)).toBe("offline");
        expect(effectiveStatus({ connection_status: "unknown", last_seen_at: null }, now)).toBe("unknown");
        expect(effectiveStatus(undefined, now)).toBe("unknown");
    });
});
