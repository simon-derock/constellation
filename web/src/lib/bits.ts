const HEX64 = /^[0-9a-fA-F]{64}$/;

// 256 bits, most significant first: row-major on the 16x16 grid, so a hash always draws the same picture
export function hexToBits(hex: string): boolean[] {
  if (!HEX64.test(hex)) throw new Error("a hash is 64 hexadecimal characters");
  const bits: boolean[] = [];
  for (const char of hex) {
    const nibble = Number.parseInt(char, 16);
    for (let shift = 3; shift >= 0; shift -= 1) bits.push(((nibble >> shift) & 1) === 1);
  }
  return bits;
}

export function diffBits(a: string, b: string): number[] {
  const left = hexToBits(a);
  const right = hexToBits(b);
  return left.flatMap((bit, i) => (bit === right[i] ? [] : [i]));
}

// one picture for a whole answer: SHA-256 over the query hashes, each length-prefixed so that
// ["ab", "c"] and ["a", "bc"] cannot seal to the same value
export async function sealHash(hashes: readonly string[]): Promise<string> {
  const text = hashes.map((h) => `${h.length}:${h}`).join("|");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
