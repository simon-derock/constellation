import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, ask, replay } from "./api";

function reply(status: number, body: unknown): void {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

afterEach(() => vi.unstubAllGlobals());

const request = { tenant: "apex", kind: "SILENCE", question: "q" } as const;

describe("api errors", () => {
  it("explains a rate limit as a wait, not a failure", async () => {
    reply(429, { detail: "rate limit reached; try again shortly" });
    await expect(ask(request)).rejects.toMatchObject({ status: 429, message: expect.stringContaining("wait") });
  });

  it("passes the server's own words for an unavailable model", async () => {
    reply(503, { detail: "the model is unavailable right now; recorded runs are still browsable" });
    await expect(ask(request)).rejects.toMatchObject({ status: 503, message: expect.stringContaining("recorded runs") });
  });

  it("names a rejected question as such", async () => {
    reply(422, { detail: "a perspective question needs a known actor and a day" });
    const error = await ask(request).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toContain("needs a known actor");
  });

  it("survives a response that is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502 })));
    await expect(replay({ tenant: "apex", queries: [] })).rejects.toMatchObject({ status: 502 });
  });

  it("reports an unreachable server in plain words", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("network"))));
    await expect(ask(request)).rejects.toMatchObject({ status: 0, message: expect.stringContaining("reach") });
  });
});

describe("actions api", () => {
  it("says what a refused operator key means in plain words", async () => {
    reply(403, { detail: "real actions need the operator key" });
    const { approveAction } = await import("./api");
    await expect(approveAction("a1", "real", "wrong")).rejects.toMatchObject({
      status: 403,
      message: expect.stringContaining("operator key"),
    });
  });

  it("explains a decided action as already decided", async () => {
    reply(409, { detail: "this action was already decided" });
    const { approveAction } = await import("./api");
    await expect(approveAction("a1", "dry-run")).rejects.toMatchObject({
      status: 409,
      message: expect.stringContaining("already decided"),
    });
  });

  it("sends the operator key only for real approvals, and never in the body", async () => {
    const fetcher = vi.fn(async (_url: string, _init?: RequestInit) => new Response(JSON.stringify({ id: "a1", status: "executed" }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const { approveAction } = await import("./api");
    await approveAction("a1", "dry-run", "ignored");
    await approveAction("a1", "real", "s3cret");
    const [dry, real] = fetcher.mock.calls.map((call) => call[1]);
    expect((dry?.headers as Record<string, string>)["x-approver-key"]).toBeUndefined();
    expect((real?.headers as Record<string, string>)["x-approver-key"]).toBe("s3cret");
    expect(String(real?.body)).not.toContain("s3cret");
  });
});
