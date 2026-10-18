import { useId } from "react";

const TAU = Math.PI * 2;
const C = 200;
const f = (n: number) => n.toFixed(2);
const at = (r: number, a: number): [number, number] => [C + r * Math.sin(a), C - r * Math.cos(a)];

// a straight, tapering ray: base width w (radians at r0), pointed at r1
function dagger(a: number, r0: number, r1: number, w: number): string {
  const [bx, by] = at(r0, a - w);
  const [cx, cy] = at(r0, a + w);
  const [tx, ty] = at(r1, a);
  return `M${f(bx)} ${f(by)}L${f(tx)} ${f(ty)}L${f(cx)} ${f(cy)}Z`;
}

// a wavy ray, as in heraldic suns: the centre line swings side to side and the width tapers to nothing
function flame(a: number, r0: number, r1: number, w: number, swing: number): string {
  const left: string[] = [];
  const right: string[] = [];
  const steps = 22;
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps;
    const r = r0 + (r1 - r0) * t;
    const offset = (swing * Math.sin(t * TAU * 2.25)) / r;
    const half = w * (1 - t) ** 0.8;
    left.push(at(r, a + offset - half).map(f).join(" "));
    right.push(at(r, a + offset + half).map(f).join(" "));
  }
  return `M${left.join("L")}L${right.reverse().join("L")}Z`;
}

const range = (n: number) => Array.from({ length: n }, (_, i) => i);

// an antique sun: engraved rings, sixteen straight rays, sixteen wavy ones, a small ray between each
export function Sun() {
  const id = useId();
  const disc = `${id}-disc`;
  const rough = `${id}-rough`;
  return (
    <svg viewBox="0 0 400 400" role="img" aria-label="A gilded sun" className="fig-art">
      <defs>
        <radialGradient id={disc} cx="42%" cy="38%" r="70%">
          <stop offset="0" stopColor="#f6e7b0" />
          <stop offset="0.55" stopColor="#d8b25a" />
          <stop offset="1" stopColor="#a67b2b" />
        </radialGradient>
        <filter id={rough} x="-5%" y="-5%" width="110%" height="110%">
          <feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="7" />
          <feDisplacementMap in="SourceGraphic" scale="2.4" />
        </filter>
      </defs>
      <g filter={`url(#${rough})`} stroke="#8f6a22" strokeLinejoin="round">
        {range(72).map((i) => {
          const [x1, y1] = at(191, (i * TAU) / 72);
          const [x2, y2] = at(i % 3 === 0 ? 198 : 195, (i * TAU) / 72);
          return <line key={`t${i}`} x1={f(x1)} y1={f(y1)} x2={f(x2)} y2={f(y2)} strokeWidth="0.7" />;
        })}
        {range(32).map((i) => (
          <path key={`s${i}`} d={dagger(((i + 0.5) * TAU) / 32, 104, 132, 0.04)} fill="#e9d089" strokeWidth="0.6" />
        ))}
        {range(16).map((i) => (
          <path key={`f${i}`} d={flame(((i + 0.5) * TAU) / 16, 104, 170, 0.075, 6)} fill="#f0dc9c" strokeWidth="0.9" />
        ))}
        {range(16).map((i) => (
          <g key={`d${i}`}>
            <path d={dagger((i * TAU) / 16, 104, 188, 0.085)} fill="#c99a3e" strokeWidth="0.9" />
            <line
              x1={f(at(108, (i * TAU) / 16)[0])}
              y1={f(at(108, (i * TAU) / 16)[1])}
              x2={f(at(176, (i * TAU) / 16)[0])}
              y2={f(at(176, (i * TAU) / 16)[1])}
              stroke="#f4e6b4"
              strokeWidth="0.8"
            />
          </g>
        ))}
        <circle cx={C} cy={C} r="108" fill="#f3e4ac" strokeWidth="1.6" />
        <circle cx={C} cy={C} r="101" fill="none" strokeWidth="0.7" strokeDasharray="1 3.2" />
        <circle cx={C} cy={C} r="94" fill={`url(#${disc})`} strokeWidth="1.2" />
        <circle cx={C} cy={C} r="80" fill="none" strokeWidth="0.7" />
        {range(24).map((i) => {
          const [x1, y1] = at(24, (i * TAU) / 24);
          const [x2, y2] = at(i % 2 ? 64 : 76, (i * TAU) / 24);
          return <line key={`h${i}`} x1={f(x1)} y1={f(y1)} x2={f(x2)} y2={f(y2)} strokeWidth="0.6" opacity="0.5" />;
        })}
        <circle cx={C} cy={C} r="14" fill="#f8edc2" strokeWidth="1" />
        <circle cx={C} cy={C} r="5" fill="#a67b2b" stroke="none" />
      </g>
    </svg>
  );
}

const STARS: [number, number, number][] = [
  [322, 64, 11],
  [358, 148, 6],
  [338, 238, 5],
  [296, 318, 8],
  [224, 362, 5],
  [96, 330, 7],
  [60, 120, 9],
  [128, 52, 5],
];
const LINES: [number, number][] = [
  [7, 0],
  [0, 1],
  [1, 2],
  [2, 3],
  [3, 4],
  [6, 7],
  [5, 6],
];

function sparkle(x: number, y: number, s: number): string {
  return `M${x} ${y - s}Q${x} ${y} ${x + s} ${y}Q${x} ${y} ${x} ${y + s}Q${x} ${y} ${x - s} ${y}Q${x} ${y} ${x} ${y - s}Z`;
}

// a crescent moon engraved with contour lines along its shadow, and a small constellation joined by dotted lines
export function Moon() {
  const id = useId();
  const body = `${id}-body`;
  const mask = `${id}-mask`;
  const clip = `${id}-clip`;
  const rough = `${id}-rough`;
  return (
    <svg viewBox="0 0 400 400" role="img" aria-label="A crescent moon among joined stars" className="fig-art">
      <defs>
        <radialGradient id={body} cx="30%" cy="40%" r="80%">
          <stop offset="0" stopColor="#fbf5df" />
          <stop offset="0.6" stopColor="#e6d8b0" />
          <stop offset="1" stopColor="#bfae7c" />
        </radialGradient>
        <mask id={mask}>
          <rect width="400" height="400" fill="#fff" />
          <circle cx="238" cy="186" r="96" fill="#000" />
        </mask>
        <clipPath id={clip}>
          <circle cx="190" cy="206" r="112" />
        </clipPath>
        <filter id={rough} x="-5%" y="-5%" width="110%" height="110%">
          <feTurbulence type="fractalNoise" baseFrequency="0.04" numOctaves="2" seed="11" />
          <feDisplacementMap in="SourceGraphic" scale="2" />
        </filter>
      </defs>
      <g filter={`url(#${rough})`} stroke="#8f6a22" strokeLinejoin="round">
        <circle cx="190" cy="206" r="112" fill="none" strokeWidth="0.7" strokeDasharray="2 5" opacity="0.55" />
        <g mask={`url(#${mask})`}>
          <circle cx="190" cy="206" r="112" fill={`url(#${body})`} strokeWidth="1.4" />
        </g>
        <g clipPath={`url(#${clip})`} fill="none" strokeWidth="0.6" opacity="0.7">
          {range(9).map((i) => (
            <circle key={`c${i}`} cx="238" cy="186" r={100 + i * 4.2} opacity={1 - i * 0.09} />
          ))}
        </g>
        {LINES.map(([a, b]) => (
          <line
            key={`l${a}-${b}`}
            x1={STARS[a]![0]}
            y1={STARS[a]![1]}
            x2={STARS[b]![0]}
            y2={STARS[b]![1]}
            strokeWidth="0.8"
            strokeDasharray="1 4"
            strokeLinecap="round"
          />
        ))}
        {STARS.map(([x, y, s]) => (
          <g key={`${x}-${y}`}>
            <path d={sparkle(x, y, s)} fill="#d9b45a" strokeWidth="0.7" />
            <circle cx={x} cy={y} r="1.6" fill="#8f6a22" stroke="none" />
          </g>
        ))}
      </g>
    </svg>
  );
}

// the two figures that flank a title; `hero` is the large pair of the home page, `page` the smaller pair of the others
export function Figures({ size }: { size: "hero" | "page" }) {
  return (
    <div className={`figures figures-${size}`} aria-hidden="false">
      <div className="fig fig-left">
        <div className="fig-float fig-float-a">
          <Sun />
        </div>
      </div>
      <div className="fig fig-right">
        <div className="fig-float fig-float-b">
          <Moon />
        </div>
      </div>
    </div>
  );
}
