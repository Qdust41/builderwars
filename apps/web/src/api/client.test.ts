import { describe, expect, it } from "vitest";
import { ApiClient, ApiError, devUserAuth, type Fetch } from "./client";

function fakeFetch(status: number, body: unknown, calls: [string, RequestInit | undefined][]): Fetch {
  return async (input, init) => {
    calls.push([input, init]);
    return new Response(JSON.stringify(body), { status });
  };
}

describe("ApiClient", () => {
  it("sends the dev identity header and JSON body", async () => {
    const calls: [string, RequestInit | undefined][] = [];
    const client = new ApiClient("/api", devUserAuth("alice"), fakeFetch(201, { id: "prj_1" }, calls));
    const project = await client.createProject("Rover");
    expect(project.id).toBe("prj_1");
    const [url, init] = calls[0];
    expect(url).toBe("/api/projects");
    expect(init?.method).toBe("POST");
    expect((init?.headers as Record<string, string>)["X-Dev-User"]).toBe("alice");
    expect(init?.body).toBe(JSON.stringify({ name: "Rover" }));
  });

  it("raises ApiError with status and detail", async () => {
    const client = new ApiClient("/api", devUserAuth("bob"), fakeFetch(404, { detail: "nope" }, []));
    await expect(client.getProject("prj_x")).rejects.toMatchObject({ status: 404 });
    await expect(client.getProject("prj_x")).rejects.toBeInstanceOf(ApiError);
  });

  it("encodes path parameters", async () => {
    const calls: [string, RequestInit | undefined][] = [];
    const client = new ApiClient("", devUserAuth("a"), fakeFetch(200, {}, calls));
    await client.getDevice("a/b");
    expect(calls[0][0]).toBe("/devices/a%2Fb");
  });
});
