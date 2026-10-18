// formations: deterministic target points sampled from a silhouette
import type { Formation } from "./types";


const R = 340;

// van der Corput radical inverse — even, deterministic point spread
function halton(i: number, base: number) {
  let f = 1;
  let r = 0;
  let k = i + 1;
  while (k > 0) {
    f /= base;
    r += f * (k % base);
    k = Math.floor(k / base);
  }
  return r;
}

function seeded(id: string, salt: number) {
  let h = 2166136261 ^ salt;
  for (let i = 0; i < id.length; i++) h = (h ^ id.charCodeAt(i)) * 16777619;
  h >>>= 0;
  return () => {
    h = (h * 1664525 + 1013904223) >>> 0;
    return h / 4294967296;
  };
}

// ---------------- brain silhouette (sagittal, facing left) ----------------
// A hand-drawn anatomical contour: frontal pole, parietal crown, occipital
// curve, preoccipital notch, cerebellum, brain stem and temporal lobe.
// Nodes ride the contour and a concentric inner ribbon, so the silhouette
// reads as cortex — outline plus cortical band, never a filled blob.

const BRAIN: [number, number][] = [
  [-1.0, 0.02],
  [-0.97, -0.28],
  [-0.83, -0.5],
  [-0.56, -0.66],
  [-0.2, -0.74],
  [0.2, -0.68],
  [0.54, -0.5],
  [0.79, -0.22],
  [0.86, 0.06],
  [0.72, 0.19],
  [0.87, 0.33],
  [0.8, 0.55],
  [0.6, 0.66],
  [0.41, 0.57],
  [0.31, 0.73],
  [0.17, 0.88],
  [0.03, 0.84],
  [0.11, 0.6],
  [0.06, 0.43],
  [-0.16, 0.52],
  [-0.47, 0.5],
  [-0.72, 0.35],
  [-0.93, 0.16],
];

const BRAIN_CX = 0.0;
const BRAIN_CY = -0.02;

const BRAIN_SEG = (() => {
  const seg: number[] = [];
  let total = 0;
  for (let i = 0; i < BRAIN.length; i++) {
    const a = BRAIN[i]!;
    const b = BRAIN[(i + 1) % BRAIN.length]!;
    const d = Math.hypot(b[0] - a[0], b[1] - a[1]);
    seg.push(d);
    total += d;
  }
  return { seg, total };
})();

// evenly spaced point along the contour, optionally shrunk toward the centroid
function brainContour(k: number, total: number, shrink = 1) {
  const u = (k % Math.max(1, total)) / Math.max(1, total);
  let d = u * BRAIN_SEG.total;
  let i = 0;
  while (i < BRAIN_SEG.seg.length - 1 && d > BRAIN_SEG.seg[i]!) {
    d -= BRAIN_SEG.seg[i]!;
    i++;
  }
  const a = BRAIN[i]!;
  const b = BRAIN[(i + 1) % BRAIN.length]!;
  const t = d / Math.max(1e-6, BRAIN_SEG.seg[i]!);
  const px = a[0] + (b[0] - a[0]) * t;
  const py = a[1] + (b[1] - a[1]) * t;
  return {
    x: BRAIN_CX + (px - BRAIN_CX) * shrink,
    y: BRAIN_CY + (py - BRAIN_CY) * shrink,
  };
}

export function formationTargets(
  formation: Formation,
  nodes: { id: string }[],
): Map<string, { x: number; y: number }> {
  const out = new Map<string, { x: number; y: number }>();
  const n = Math.max(1, nodes.length);
  nodes.forEach((node, i) => {
    const r = seeded(node.id, formation.length * 7 + 11);
    let x = 0;
    let y = 0;
    if (formation === "brain") {
// three concentric bands: silhouette, cortical ribbon, deep tissue
      const band = i % 5;
      const shrink = band < 3 ? 1 : band === 3 ? 0.72 : 0.45;
      const per = band < 3 ? Math.ceil((n * 3) / 5) : Math.ceil(n / 5);
      const k = band < 3 ? Math.floor(i / 5) * 3 + band : Math.floor(i / 5);
      const off = band === 3 ? 0.5 : band === 4 ? 1.4 : 0;
      const p = brainContour(k + off, Math.max(8, per), shrink);
      x = p.x * 1.4;
      y = p.y * 1.4;
    } else if (formation === "moon") {

      if (i % 3 === 0) {
        // outer limb
        const t = (Math.floor(i / 3) / Math.ceil(n / 3)) * Math.PI * 2;
        x = Math.cos(t) * 1.25;
        y = Math.sin(t) * 1.25;
      } else {
        for (let t = 0; t < 96; t++) {
          const px = halton(i * 47 + t, 2) * 2 - 1;
          const py = halton(i * 47 + t, 3) * 2 - 1;
          const inOuter = px * px + py * py <= 1;
          const inCut = (px - 0.42) ** 2 + (py + 0.06) ** 2 <= 0.72 ** 2;
          if (inOuter && !inCut) {
            x = px * 1.25;
            y = py * 1.25;
            break;
          }
        }
      }
    } else if (formation === "orbit") {
      const rings = 5;
      const ring = i % rings;
      const per = Math.ceil(n / rings);
      const a = ((Math.floor(i / rings) % per) / per) * Math.PI * 2 + ring * 0.7;
      const rad = 0.32 + ring * 0.2 + (r() - 0.5) * 0.045;
      x = Math.cos(a) * rad * 1.5;
      y = Math.sin(a) * rad * 0.92;
    } else if (formation === "culture") {
// cultured tissue field: jittered hex lattice, evenly seeded
      const cols = Math.max(3, Math.round(Math.sqrt(n * 2.1)));
      const rows = Math.ceil(n / cols);
      const cx = i % cols;
      const cy = Math.floor(i / cols);
      const stagger = cy % 2 ? 0.5 : 0;
      x = ((cx + 0.5 + stagger) / cols - 0.5) * 2.9 + (r() - 0.5) * 0.16;
      y = ((cy + 0.5) / Math.max(1, rows) - 0.5) * 1.85 + (r() - 0.5) * 0.16;
    } else {
      return;
    }
    out.set(node.id, { x: x * R, y: y * R });
  });
  return out;
}




