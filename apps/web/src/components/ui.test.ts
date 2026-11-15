import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { errorText, initials, timeAgo } from "./ui";

describe("errorText", () => {
  it("unquotes a string detail from the API", () => {
    expect(errorText(new ApiError(422, '"project name must not be blank"'))).toBe(
      "project name must not be blank",
    );
  });
  it("strips the Error: prefix from stringified errors", () => {
    expect(errorText(String(new Error("boom")))).toBe("boom");
  });
});

describe("timeAgo", () => {
  const now = Date.parse("2026-11-15T12:00:00Z");
  it("says never for a missing time", () => expect(timeAgo(null, now)).toBe("never"));
  it("says just now under a minute", () =>
    expect(timeAgo("2026-11-15T11:59:40Z", now)).toBe("just now"));
  it("uses minutes and hours", () => {
    expect(timeAgo("2026-11-15T11:55:00Z", now)).toMatch(/5 minutes ago/);
    expect(timeAgo("2026-11-15T09:00:00Z", now)).toMatch(/3 hours ago/);
  });
});

describe("initials", () => {
  it("uses the email's local part", () => {
    expect(initials("ada.lovelace@example.com")).toBe("AL");
    expect(initials("qd@example.com")).toBe("QD");
  });
});
