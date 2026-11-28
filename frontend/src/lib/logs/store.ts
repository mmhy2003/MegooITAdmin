import type { LevelGroup } from "@/lib/logs/levels";

export type LineRow = {
  kind: "line";
  key: string;
  source: string;
  run: number;
  seq: number;
  time: string;
  ms: number;
  text: string;
  plain: string;
  level: LevelGroup;
  unit: string | null;
  truncated: boolean;
};
export type MarkerRow = {
  kind: "marker";
  key: string;
  source: string;
  ms: number;
  marker: "skipped" | "reconnected";
  count: number;
};
export type Row = LineRow | MarkerRow;
