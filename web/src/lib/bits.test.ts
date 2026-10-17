import { describe, expect, it } from "vitest";
import { diffBits, hexToBits, sealHash } from "./bits";

const ZERO = "0".repeat(64);
const ONES = "f".repeat(64);

describe("hexToBits", () => {
  it("turns 64 hex characters into 256 bits, most significant first", () => {
    const bits = hexToBits("8" + "0".repeat(63));
    expect(bits).toHaveLength(256);
    expect(bits[0]).toBe(true);
    expect(bits.slice(1).some(Boolean)).toBe(false);
    expect(hexToBits(ONES).every(Boolean)).toBe(true);
  });

  it("reads the last nibble into the last four bits", () => {
    const bits = hexToBits("0".repeat(63) + "5");
    expect(bits.slice(252)).toEqual([false, true, false, true]);
  });

  it.each(["", "abc", "z".repeat(64), "A".repeat(63)])("refuses %j", (bad) => {
    expect(() => hexToBits(bad)).toThrow(/64 hexadecimal/);
  });

  it("accepts upper-case hex", () => {
    expect(hexToBits("A".repeat(64))).toEqual(hexToBits("a".repeat(64)));
  });
});

describe("diffBits", () => {
  it("lists exactly the positions whose bits differ", () => {
    expect(diffBits(ZERO, ZERO)).toEqual([]);
    expect(diffBits(ZERO, ONES)).toHaveLength(256);
    expect(diffBits(ZERO, "8" + "0".repeat(63))).toEqual([0]);
    expect(diffBits(ZERO, "0".repeat(63) + "1")).toEqual([255]);
  });
});

describe("sealHash", () => {
  it("is deterministic and depends on the order of the query hashes", async () => {
    const a = await sealHash(["aa", "bb"]);
    expect(a).toMatch(/^[0-9a-f]{64}$/);
    expect(await sealHash(["aa", "bb"])).toBe(a);
    expect(await sealHash(["bb", "aa"])).not.toBe(a);
  });

  it("does not collide when the same characters are split differently", async () => {
    expect(await sealHash(["ab", "c"])).not.toBe(await sealHash(["a", "bc"]));
  });
});
