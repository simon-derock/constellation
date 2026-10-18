import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const SHAPE = /^[a-z0-9-]{8,64}$/;

// the module keeps an id for pages whose storage is blocked, so each test starts from a fresh module
async function load() {
  vi.resetModules();
  return (await import("./session")).sessionId;
}

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("sessionId", () => {
  it("makes a lowercase id the server will accept", async () => {
    const sessionId = await load();
    expect(sessionId()).toMatch(SHAPE);
  });

  it("keeps the same id for the whole tab, across page loads", async () => {
    const first = (await load())();
    const afterReload = (await load())();
    expect(afterReload).toBe(first);
    expect(sessionStorage.getItem("constellation.session")).toBe(first);
  });

  it("never sends a stored value the server would refuse", async () => {
    sessionStorage.setItem("constellation.session", "NOT VALID!");
    const id = (await load())();
    expect(id).toMatch(SHAPE);
    expect(sessionStorage.getItem("constellation.session")).toBe(id);
  });

  it("still gives one stable id for the page when storage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const sessionId = await load();
    const id = sessionId();
    expect(id).toMatch(SHAPE);
    expect(sessionId()).toBe(id);
  });

  it("falls back to random bytes where randomUUID does not exist", async () => {
    // insecure contexts (plain http) expose no randomUUID
    Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true });
    try {
      const id = (await load())();
      expect(id).toMatch(SHAPE);
      expect(id).toHaveLength(32);
    } finally {
      Reflect.deleteProperty(crypto, "randomUUID");
    }
  });
});
