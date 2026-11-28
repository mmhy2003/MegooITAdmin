import { describe, expect, it } from "vitest";
import { nearest16, parseAnsi, type Segment, segmentClass, stripAnsi } from "@/lib/logs/ansi";

const PLAIN = { fg: null, bold: false, dim: false, italic: false, underline: false };

function seg(text: string, style: Partial<Omit<Segment, "text">> = {}): Segment {
  return { text, ...PLAIN, ...style };
}

describe("parseAnsi", () => {
  it("gives one plain segment for text without escapes", () => {
    expect(parseAnsi("hello")).toEqual([seg("hello")]);
  });

  it("gives no segment for empty text", () => {
    expect(parseAnsi("")).toEqual([]);
  });

  it.each([...Array(8).keys()])("reads foreground %i from 3x and 9x", (n) => {
    expect(parseAnsi(`\x1b[${30 + n}ma`)).toEqual([seg("a", { fg: n })]);
    expect(parseAnsi(`\x1b[${90 + n}ma`)).toEqual([seg("a", { fg: n + 8 })]);
  });

  it("reads bold, dim, italic and underline", () => {
    expect(parseAnsi("\x1b[1ma\x1b[2mb\x1b[3mc\x1b[4md")).toEqual([
      seg("a", { bold: true }),
      seg("b", { bold: true, dim: true }),
      seg("c", { bold: true, dim: true, italic: true }),
      seg("d", { bold: true, dim: true, italic: true, underline: true }),
    ]);
  });

  it("resets everything on 0 and on an empty SGR", () => {
    expect(parseAnsi("\x1b[1;31ma\x1b[0mb\x1b[4mc\x1b[md")).toEqual([
      seg("a", { fg: 1, bold: true }),
      seg("b"),
      seg("c", { underline: true }),
      seg("d"),
    ]);
  });

  it("turns styles off with 22, 23, 24 and 39", () => {
    expect(parseAnsi("\x1b[1;2;3;4;32ma\x1b[22mb\x1b[23mc\x1b[24md\x1b[39me")).toEqual([
      seg("a", { fg: 2, bold: true, dim: true, italic: true, underline: true }),
      seg("b", { fg: 2, italic: true, underline: true }),
      seg("c", { fg: 2, underline: true }),
      seg("d", { fg: 2 }),
      seg("e"),
    ]);
  });

  it("maps 256 colours and true colours to the nearest of 16", () => {
    expect(parseAnsi("\x1b[38;5;196ma")).toEqual([seg("a", { fg: 9 })]);
    expect(parseAnsi("\x1b[38;5;244ma")).toEqual([seg("a", { fg: 8 })]);
    expect(parseAnsi("\x1b[38;5;3ma")).toEqual([seg("a", { fg: 3 })]);
    expect(parseAnsi("\x1b[38;2;0;205;0ma")).toEqual([seg("a", { fg: 2 })]);
  });

  it("ignores backgrounds, with their arguments", () => {
    expect(parseAnsi("\x1b[41ma\x1b[101mb\x1b[48;5;196mc\x1b[48;2;1;2;3;1md\x1b[49me")).toEqual([
      seg("abc"),
      seg("de", { bold: true }),
    ]);
  });

  it("ignores unknown codes", () => {
    expect(parseAnsi("\x1b[5;31ma")).toEqual([seg("a", { fg: 1 })]);
  });

  it("strips OSC, cursor moves, charset escapes and C0 controls but keeps tabs", () => {
    const text = "\x1b]0;title\x07a\x1b]8;;http://x\x1b\\b\x1b[2K\x1b[1Ac\x1b(Bd\x1bMe\x00\x08\r\x7ff\tg";
    expect(parseAnsi(text)).toEqual([seg("abcdef\tg")]);
  });

  it("merges adjacent segments of the same style", () => {
    expect(parseAnsi("\x1b[31ma\x1b[31mb\x1b[1m\x1b[22mc\x1b[0md")).toEqual([seg("abc", { fg: 1 }), seg("d")]);
  });
});

describe("stripAnsi", () => {
  it("leaves only the text", () => {
    expect(stripAnsi("\x1b[1;31mERROR\x1b[0m boom\x1b]0;t\x07\r")).toBe("ERROR boom");
  });
});

describe("nearest16", () => {
  it("picks the closest xterm colour", () => {
    expect(nearest16(0, 0, 0)).toBe(0);
    expect(nearest16(255, 0, 0)).toBe(9);
    expect(nearest16(200, 0, 0)).toBe(1);
    expect(nearest16(128, 128, 128)).toBe(8);
    expect(nearest16(250, 250, 250)).toBe(15);
  });
});

describe("segmentClass", () => {
  it("names the colour and each style", () => {
    expect(segmentClass(seg("a"))).toBe("");
    expect(segmentClass(seg("a", { fg: 9, bold: true }))).toBe("ansi-fg-9 ansi-bold");
    expect(segmentClass(seg("a", { fg: 0, bold: true, dim: true, italic: true, underline: true }))).toBe(
      "ansi-fg-0 ansi-bold ansi-dim ansi-italic ansi-underline",
    );
  });
});
