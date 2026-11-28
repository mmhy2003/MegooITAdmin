"use client";

import { PlusIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { compileFilter } from "@/lib/logs/filter";
import { LEVEL_GROUPS, LEVEL_LABELS, type LevelGroup } from "@/lib/logs/levels";
import { MAX_FILTER, type ViewSettings } from "@/lib/logs/sources";

/** Typing waits this long after the last key before the filter changes. */
const DEBOUNCE_MS = 200;

function Toggle({ pressed, onClick, children }: { pressed: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <Button size="sm" variant={pressed ? "default" : "outline"} aria-pressed={pressed} onClick={onClick}>
      {children}
    </Button>
  );
}

function isInvalid(q: string, regex: boolean): boolean {
  const compiled = compileFilter(q, regex);
  return compiled !== null && "error" in compiled;
}

/**
 * The viewer's settings: the filter and its regex switch, the lines it matches, the levels, the layout, wrap and the
 * time zone. The field holds what is typed and hands it on 200 ms after the last key; an invalid regex stays in the
 * field, marked, and the last valid filter stays in force.
 */
export function LogToolbar({ settings, onSettings, matched, total, onAddSource, extra }: {
  settings: ViewSettings;
  onSettings: (next: ViewSettings) => void;
  matched: number;
  total: number;
  onAddSource?: () => void;
  extra?: ReactNode;
}) {
  const errorId = useId();
  const [text, setText] = useState(settings.q);
  const [regex, setRegex] = useState(settings.regex);
  // A filter that comes from outside (a view opened, a link) replaces what the field holds.
  const [given, setGiven] = useState({ q: settings.q, regex: settings.regex });
  if (given.q !== settings.q || given.regex !== settings.regex) {
    setGiven({ q: settings.q, regex: settings.regex });
    setText(settings.q);
    setRegex(settings.regex);
  }
  const invalid = isInvalid(text, regex);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef(settings);
  useEffect(() => {
    latest.current = settings;
  }, [settings]);
  useEffect(() => () => {
    if (timer.current !== null) clearTimeout(timer.current);
  }, []);

  function cancel() {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }

  function type(value: string) {
    setText(value);
    cancel();
    if (isInvalid(value, regex)) return;
    timer.current = setTimeout(() => {
      timer.current = null;
      onSettings({ ...latest.current, q: value, regex });
    }, DEBOUNCE_MS);
  }

  function switchRegex() {
    const next = !regex;
    setRegex(next);
    cancel();
    if (!isInvalid(text, next)) onSettings({ ...settings, q: text, regex: next });
  }

  function switchLevel(level: LevelGroup) {
    const on = settings.levels.includes(level);
    const levels = LEVEL_GROUPS.filter((l) => (l === level ? !on : settings.levels.includes(l)));
    onSettings({ ...settings, levels });
  }

  const counting = settings.q !== "" || settings.levels.length < LEVEL_GROUPS.length;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex min-w-60 flex-1 flex-col gap-1">
        <div className="flex items-center gap-2">
          <Input aria-label="Filter" placeholder="Filter lines" value={text} maxLength={MAX_FILTER}
            aria-invalid={invalid || undefined} aria-describedby={invalid ? errorId : undefined}
            onChange={(e) => type(e.target.value)} />
          <Toggle pressed={regex} onClick={switchRegex}>Regex</Toggle>
        </div>
        {invalid && <p id={errorId} className="text-sm text-destructive">Not a valid regular expression</p>}
      </div>
      {counting && (
        <span className="text-sm text-muted-foreground">
          {matched.toLocaleString("en-US")} of {total.toLocaleString("en-US")} lines match
        </span>
      )}
      <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Levels">
        {LEVEL_GROUPS.map((level) => (
          <Toggle key={level} pressed={settings.levels.includes(level)} onClick={() => switchLevel(level)}>
            {LEVEL_LABELS[level]}
          </Toggle>
        ))}
      </div>
      <div className="flex items-center gap-1" role="group" aria-label="Layout">
        <Toggle pressed={settings.layout === "side_by_side"}
          onClick={() => onSettings({ ...settings, layout: "side_by_side" })}>Side by side</Toggle>
        <Toggle pressed={settings.layout === "merged"} onClick={() => onSettings({ ...settings, layout: "merged" })}>
          Merged
        </Toggle>
      </div>
      <Toggle pressed={settings.wrap} onClick={() => onSettings({ ...settings, wrap: !settings.wrap })}>Wrap</Toggle>
      <div className="flex items-center gap-1" role="group" aria-label="Time zone">
        <Toggle pressed={!settings.utc} onClick={() => onSettings({ ...settings, utc: false })}>Local</Toggle>
        <Toggle pressed={settings.utc} onClick={() => onSettings({ ...settings, utc: true })}>UTC</Toggle>
      </div>
      {onAddSource && (
        <Button size="sm" onClick={onAddSource}>
          <PlusIcon />
          Add source
        </Button>
      )}
      {extra}
    </div>
  );
}
