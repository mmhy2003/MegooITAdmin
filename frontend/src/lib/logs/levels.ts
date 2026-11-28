export type LevelGroup = "error" | "warning" | "info" | "debug" | "none";

export const LEVEL_GROUPS: readonly LevelGroup[] = ["error", "warning", "info", "debug", "none"];
export const LEVEL_LABELS: Record<LevelGroup, string> = {
  error: "Error",
  warning: "Warning",
  info: "Info",
  debug: "Debug",
  none: "No level",
};
export const LEVEL_TAGS: Record<LevelGroup, string> = { error: "ERR", warning: "WRN", info: "INF", debug: "DBG", none: "" };

const PRIORITY_GROUPS: Record<string, LevelGroup> = {
  emerg: "error",
  alert: "error",
  crit: "error",
  err: "error",
  warning: "warning",
  notice: "info",
  info: "info",
  debug: "debug",
};

const WORD_GROUPS: Record<string, LevelGroup> = {
  fatal: "error",
  critical: "error",
  panic: "error",
  emerg: "error",
  alert: "error",
  error: "error",
  err: "error",
  warning: "warning",
  warn: "warning",
  info: "info",
  notice: "info",
  debug: "debug",
  trace: "debug",
};

const WORDS = "fatal|critical|panic|emerg|alert|error|err|warning|warn|info|notice|debug|trace";

/** The four ways a line names its level; the one found earliest in the line wins. */
const PATTERNS = [
  /\b(FATAL|CRITICAL|ERROR|ERR|WARNING|WARN|INFO|NOTICE|DEBUG|TRACE)\b/,
  new RegExp(`\\[(${WORDS})\\]`, "i"),
  new RegExp(`\\b(?:level|lvl)=["']?(${WORDS})\\b`, "i"),
  new RegExp(`"level"\\s*:\\s*"(${WORDS})"`, "i"),
];

/** How far into a line its level is looked for. */
const LOOK_AHEAD = 200;

/** The group of a journal priority, `none` for one we do not know. */
export function groupOfPriority(priority: string): LevelGroup {
  return PRIORITY_GROUPS[priority] ?? "none";
}

/** The level of a line: its journal priority when it has one, otherwise the earliest level word of its first 200 characters. */
export function levelOf(priority: string | null | undefined, plain: string): LevelGroup {
  if (priority) return groupOfPriority(priority);
  const head = plain.slice(0, LOOK_AHEAD);
  let best: RegExpExecArray | null = null;
  for (const pattern of PATTERNS) {
    const match = pattern.exec(head);
    if (match && (best === null || match.index < best.index)) best = match;
  }
  return best ? WORD_GROUPS[best[1].toLowerCase()] : "none";
}
