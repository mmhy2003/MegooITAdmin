import { describe, expect, it } from "vitest";
import { groupOfPriority, LEVEL_GROUPS, LEVEL_LABELS, LEVEL_TAGS, levelOf } from "@/lib/logs/levels";

describe("groupOfPriority", () => {
  it.each([
    ["emerg", "error"],
    ["alert", "error"],
    ["crit", "error"],
    ["err", "error"],
    ["warning", "warning"],
    ["notice", "info"],
    ["info", "info"],
    ["debug", "debug"],
    ["verbose", "none"],
    ["", "none"],
  ])("maps %s to %s", (priority, group) => {
    expect(groupOfPriority(priority)).toBe(group);
  });
});

describe("the groups", () => {
  it("lists five groups, each with a label and a tag", () => {
    expect(LEVEL_GROUPS).toEqual(["error", "warning", "info", "debug", "none"]);
    expect(LEVEL_LABELS.none).toBe("No level");
    expect(LEVEL_TAGS.error).toBe("ERR");
    expect(LEVEL_TAGS.none).toBe("");
  });
});

describe("levelOf", () => {
  it("lets the journal priority win over the text", () => {
    expect(levelOf("err", "INFO x")).toBe("error");
  });

  it("reads the text when there is no priority", () => {
    expect(levelOf(null, "INFO x")).toBe("info");
    expect(levelOf(undefined, "INFO x")).toBe("info");
  });

  it.each([
    ["2026 ERROR boom", "error"],
    ["a FATAL thing", "error"],
    ["WARN disk", "warning"],
    ["NOTICE x", "info"],
    ["[warn] x", "warning"],
    ["[PANIC] x", "error"],
    ["level=debug", "debug"],
    ['lvl="info"', "info"],
    ["lvl='warning' x", "warning"],
    ['{"level":"fatal"}', "error"],
    ['{"level" : "Notice"}', "info"],
    ["TRACE", "debug"],
    ["error in lower case", "none"],
    ["ERRORS are not a word", "none"],
    ["nothing here", "none"],
  ])("reads %j as %s", (plain, group) => {
    expect(levelOf(null, plain)).toBe(group);
  });

  it("looks no further than the first 200 characters", () => {
    expect(levelOf(null, `${"x".repeat(200)} ERROR`)).toBe("none");
    expect(levelOf(null, `${"x".repeat(190)} ERROR`)).toBe("error");
  });

  it("takes the earliest of two matches", () => {
    expect(levelOf(null, 'level=warn then ERROR')).toBe("warning");
    expect(levelOf(null, 'DEBUG {"level":"error"}')).toBe("debug");
    expect(levelOf(null, "[info] lvl=err")).toBe("info");
  });
});
