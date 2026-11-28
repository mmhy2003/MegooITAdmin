/** A run of text with one style. `fg` is one of the 16 terminal colours, or null for the default. */
export type Segment = { text: string; fg: number | null; bold: boolean; dim: boolean; italic: boolean; underline: boolean };

type Style = Omit<Segment, "text">;

const PLAIN: Style = { fg: null, bold: false, dim: false, italic: false, underline: false };

/** The xterm palette of the 16 colours, as [r, g, b]. */
const PALETTE: readonly (readonly [number, number, number])[] = [
  [0x00, 0x00, 0x00],
  [0xcd, 0x00, 0x00],
  [0x00, 0xcd, 0x00],
  [0xcd, 0xcd, 0x00],
  [0x00, 0x00, 0xee],
  [0xcd, 0x00, 0xcd],
  [0x00, 0xcd, 0xcd],
  [0xe5, 0xe5, 0xe5],
  [0x7f, 0x7f, 0x7f],
  [0xff, 0x00, 0x00],
  [0x00, 0xff, 0x00],
  [0xff, 0xff, 0x00],
  [0x5c, 0x5c, 0xff],
  [0xff, 0x00, 0xff],
  [0x00, 0xff, 0xff],
  [0xff, 0xff, 0xff],
];

const CUBE_LEVELS = [0, 95, 135, 175, 215, 255];

/**
 * The escape sequences, in the order they are tried: OSC (ended by BEL or ST), CSI (group 1 holds an SGR's
 * parameters), the character set and other nF escapes such as `ESC ( B`, and the two-byte escapes.
 */
const ESCAPE = /\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[([0-?]*)[ -/]*([@-~])|\x1b[ -/]+[0-~]|\x1b[@-Z\\-_]/g;

/** The C0 controls other than tab, and DEL. */
const CONTROLS = /[\x00-\x08\x0b-\x1f\x7f]/g;

/** The nearest of the 16 colours to an RGB colour, by squared distance. */
export function nearest16(r: number, g: number, b: number): number {
  let best = 0;
  let bestDistance = Infinity;
  PALETTE.forEach(([pr, pg, pb], index) => {
    const distance = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2;
    if (distance < bestDistance) {
      best = index;
      bestDistance = distance;
    }
  });
  return best;
}

function from256(n: number): number {
  if (n < 16) return n;
  if (n < 232) {
    const i = n - 16;
    return nearest16(CUBE_LEVELS[Math.floor(i / 36)], CUBE_LEVELS[Math.floor(i / 6) % 6], CUBE_LEVELS[i % 6]);
  }
  const grey = 8 + 10 * (n - 232);
  return nearest16(grey, grey, grey);
}

/** Applies the codes of one SGR sequence to a style. */
function applySgr(style: Style, params: string): Style {
  const next = { ...style };
  const codes = params === "" ? [0] : params.split(";").map((p) => (p === "" ? 0 : Number(p)));
  for (let i = 0; i < codes.length; i++) {
    const code = codes[i];
    if (code === 0) Object.assign(next, PLAIN);
    else if (code === 1) next.bold = true;
    else if (code === 2) next.dim = true;
    else if (code === 3) next.italic = true;
    else if (code === 4) next.underline = true;
    else if (code === 22) next.bold = next.dim = false;
    else if (code === 23) next.italic = false;
    else if (code === 24) next.underline = false;
    else if (code >= 30 && code <= 37) next.fg = code - 30;
    else if (code >= 90 && code <= 97) next.fg = code - 90 + 8;
    else if (code === 39) next.fg = null;
    else if (code === 38 || code === 48) {
      // An extended colour: 5;n or 2;r;g;b. A background is read only to skip its arguments.
      let colour: number | null = null;
      if (codes[i + 1] === 5 && i + 2 < codes.length) {
        colour = from256(codes[i + 2]);
        i += 2;
      } else if (codes[i + 1] === 2 && i + 4 < codes.length) {
        colour = nearest16(codes[i + 2], codes[i + 3], codes[i + 4]);
        i += 4;
      } else {
        i = codes.length;
      }
      if (code === 38 && colour !== null) next.fg = colour;
    }
  }
  return next;
}

function sameStyle(a: Style, b: Style): boolean {
  return (
    a.fg === b.fg && a.bold === b.bold && a.dim === b.dim && a.italic === b.italic && a.underline === b.underline
  );
}

/** Splits a line into styled segments, dropping every escape and control; adjacent segments of one style merge. */
export function parseAnsi(text: string): Segment[] {
  const segments: Segment[] = [];
  let style = PLAIN;
  const push = (raw: string) => {
    const clean = raw.replace(CONTROLS, "");
    if (!clean) return;
    const last = segments.at(-1);
    if (last && sameStyle(last, style)) last.text += clean;
    else segments.push({ text: clean, ...style });
  };
  let at = 0;
  for (const match of text.matchAll(ESCAPE)) {
    push(text.slice(at, match.index));
    at = match.index + match[0].length;
    if (match[2] === "m") style = applySgr(style, match[1]);
  }
  push(text.slice(at));
  return segments;
}

/** The text of a line without its escapes and controls. */
export function stripAnsi(text: string): string {
  return text.replace(ESCAPE, "").replace(CONTROLS, "");
}

/** The CSS classes of a segment's style, such as `ansi-fg-9 ansi-bold`. */
export function segmentClass(s: Segment): string {
  const names: string[] = [];
  if (s.fg !== null) names.push(`ansi-fg-${s.fg}`);
  if (s.bold) names.push("ansi-bold");
  if (s.dim) names.push("ansi-dim");
  if (s.italic) names.push("ansi-italic");
  if (s.underline) names.push("ansi-underline");
  return names.join(" ");
}
