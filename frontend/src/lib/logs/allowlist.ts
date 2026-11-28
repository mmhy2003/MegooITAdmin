import { checkPath } from "@/lib/logs/sources";

// The rules of backend/app/logs/allowlist.py. A pattern is an absolute path whose segments may hold "*" (any
// characters) and "?" (one character). A wildcard never crosses a "/", and the first segment holds none.
const PATTERN = /^\/[*?A-Za-z0-9._/@%+=:,-]{0,254}$/;

/** Whether the value is a pattern: allowed characters, the segment rule of a path, no wildcard in the first segment. */
export function checkPattern(value: string): boolean {
  if (!PATTERN.test(value) || !checkPath(value.replace(/[*?]/g, "x"))) return false;
  const first = value.slice(1).split("/")[0];
  return !first.includes("*") && !first.includes("?");
}

/**
 * Whether one segment matches one pattern segment, in O(segment × pattern). On a mismatch only the last "*" seen takes
 * one more character: a regex would backtrack into every earlier one.
 */
function glob(segment: string, pattern: string): boolean {
  let at = 0; // in the pattern
  let on = 0; // in the segment
  let star = -1; // the last "*" seen
  let after = -1; // where in the segment it stops for now
  while (on < segment.length) {
    if (at < pattern.length && pattern[at] === "*") {
      star = at;
      after = on;
      at += 1;
    } else if (at < pattern.length && (pattern[at] === "?" || pattern[at] === segment[on])) {
      at += 1;
      on += 1;
    } else if (star >= 0) {
      after += 1;
      at = star + 1;
      on = after;
    } else {
      return false;
    }
  }
  return [...pattern.slice(at)].every((char) => char === "*");
}

/** Whether the path matches one pattern, segment by segment, as the server checks it. */
export function matches(path: string, patterns: Iterable<string>): boolean {
  const segments = path.split("/");
  for (const pattern of patterns) {
    const parts = pattern.split("/");
    if (parts.length === segments.length && parts.every((part, i) => glob(segments[i], part))) return true;
  }
  return false;
}
