// graph and drawing types, ported from the Lunarbit graph frontend
export type LayerId =
  | "evidence"
  | "commerce"
  | "product"
  | "identity"
  | "financial"
  | "intelligence";

export interface GraphNode {
  id: string;
  type: string;
  layer: LayerId;
  label: string;
  weight: number;
  source_count: number;
  confidence: number;
  privacy_state: "public" | "redacted";
  scope: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relationship_type: string;
  confidence: number;
  provenance_label: string;
}


export interface Palette {
  paper: string;
  ink: string;
  edge: string;
  edgeHot: string;
  layers: Record<LayerId, string>;
// chromatic ramp used by multi-colour draw modes
  chroma: string[];
}

export interface ThemePreset {
  id: string;
  name: string;
  hint: string;
  vars: Record<string, string>;
  palette: Palette;
}


export type NodeMark =
  | "soma"
  | "orb"
  | "vertex"
  | "moon"
  | "burst"
  | "planet"
  | "ganglion"
  | "astro"
  | "arbor";
export type EdgeMark =
  | "dendrite"
  | "spectral"
  | "mesh"
  | "hair"
  | "filament"
  | "axon"
  | "varicose"
  | "tendril";
// global formation the layout is pulled into
export type Formation = "free" | "brain" | "moon" | "orbit" | "culture";


export interface VizProfile {
  id: string;
  name: string;
  hint: string;
  nodeMark: NodeMark;
  edgeMark: EdgeMark;
// layer = 6 semantic hues · chroma = per-node spectral index
  colorMode: "layer" | "chroma";
  labels: "hover" | "hubs" | "all";
  particles: boolean;
  charge: number;
  linkDistance: number;
  scale: number;
  formation: Formation;
// how hard nodes are pulled onto the formation (0 = free)
  formStrength: number;
// theme auto-selected when this style is picked (user can still override)
  preferredTheme: string;
}

