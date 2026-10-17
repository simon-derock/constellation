import { diffBits, hexToBits } from "../lib/bits";

interface Props {
  hash: string;
  // the hash a replay produced; absent until the proof has been replayed
  replayed?: string;
  label: string;
}

export type Phase = "idle" | "verified" | "mismatch";

export function phaseOf(hash: string, replayed?: string): Phase {
  if (replayed === undefined) return "idle";
  return diffBits(hash, replayed).length === 0 ? "verified" : "mismatch";
}

// 256 bits as a 16 x 16 grid: the picture of a proof. Replaying it settles matching bits into the verified colour in a
// diagonal sweep, and any bit that differs stays flagged.
export function BitGrid({ hash, replayed, label }: Props) {
  const bits = hexToBits(hash);
  const phase = phaseOf(hash, replayed);
  const differing = replayed === undefined ? new Set<number>() : new Set(diffBits(hash, replayed));
  const description =
    phase === "idle"
      ? `${label}: ${hash}`
      : phase === "verified"
        ? `${label}: replay produced identical bits`
        : `${label}: replay differs in ${differing.size} of 256 bits`;
  return (
    <svg className="bitgrid" viewBox="0 0 160 160" role="img" aria-label={description} data-phase={phase}>
      {bits.map((on, i) => {
        const column = i % 16;
        const row = Math.floor(i / 16);
        return (
          <rect
            // a position in the grid never changes meaning, so the index is a stable key
            key={i}
            x={column * 10 + 1}
            y={row * 10 + 1}
            width={8}
            height={8}
            rx={1}
            aria-hidden="true"
            data-on={on}
            data-diff={differing.has(i)}
            style={{ "--delay": `${(column + row) * 14}ms` } as React.CSSProperties}
          />
        );
      })}
    </svg>
  );
}
