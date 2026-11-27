"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { ServerGroup } from "@/lib/access";
import {
  type AlertMetric,
  type AlertRule,
  type AlertRuleInput,
  type Comparison,
  METRICS,
  ruleSentence,
  SEVERITY_LABEL,
  type Severity,
} from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";
import type { Server } from "@/lib/servers";

type Props = {
  rule?: AlertRule | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
};

type Scope = "all" | "group" | "server";
type Draft = {
  name: string;
  metric: AlertMetric;
  comparison: Comparison;
  threshold: number;
  minutes: number;
  severity: Severity;
  scope: Scope;
  groupId: string;
  serverId: string;
};

const METRIC_KEYS = Object.keys(METRICS) as AlertMetric[];
const SEVERITIES = Object.keys(SEVERITY_LABEL) as Severity[];
const COMPARISONS: { value: Comparison; label: string }[] = [
  { value: "above", label: "Above" },
  { value: "below", label: "Below" },
];
const SCOPES: { value: Scope; label: string }[] = [
  { value: "all", label: "All servers" },
  { value: "group", label: "A server group" },
  { value: "server", label: "A server" },
];
/** Answers that mean a list in the dialog is no longer true. */
const STALE_DETAILS = ["unknown_group", "unknown_server"];

function draftOf(rule: AlertRule | null): Draft {
  return {
    name: rule?.name ?? "",
    metric: rule?.metric ?? "disk.used_percent",
    comparison: rule?.comparison ?? "above",
    threshold: rule?.threshold ?? 90,
    minutes: (rule?.duration_seconds ?? 600) / 60,
    severity: rule?.severity ?? "warning",
    scope: rule?.server_id ? "server" : rule?.server_group_id ? "group" : "all",
    groupId: rule?.server_group_id ?? "",
    serverId: rule?.server_id ?? "",
  };
}

/** The rule the draft makes: Unreachable has no comparison and no limit. */
function inputOf(draft: Draft): AlertRuleInput {
  const unreachable = draft.metric === "unreachable";
  return {
    name: draft.name.trim(),
    metric: draft.metric,
    comparison: unreachable ? null : draft.comparison,
    threshold: unreachable ? null : draft.threshold,
    duration_seconds: Math.round(draft.minutes * 60),
    severity: draft.severity,
    server_group_id: draft.scope === "group" ? draft.groupId : null,
    server_id: draft.scope === "server" ? draft.serverId : null,
    enabled: true,
  };
}

const COMPARED = ["name", "metric", "comparison", "threshold", "duration_seconds", "severity"] as const;

/** The fields of `input` that differ from `rule`. The scope goes as both its fields, so the other one is cleared. */
function changesOf(rule: AlertRule, input: AlertRuleInput): Partial<AlertRuleInput> {
  const changes: Partial<AlertRuleInput> = {};
  for (const field of COMPARED) {
    if (input[field] !== rule[field]) Object.assign(changes, { [field]: input[field] });
  }
  if (input.server_group_id !== rule.server_group_id || input.server_id !== rule.server_id) {
    changes.server_group_id = input.server_group_id;
    changes.server_id = input.server_id;
  }
  return changes;
}

/** Creates an alert rule, or edits `rule`. */
export function AlertRuleDialog({ rule, open, onOpenChange, onSaved }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        {/* Keyed by the rule, and unmounted when closed, so the form always starts from the saved rule. */}
        <AlertRuleForm key={rule?.id ?? "new"} rule={rule ?? null} onSaved={onSaved} />
      </DialogContent>
    </Dialog>
  );
}

function AlertRuleForm({ rule, onSaved }: { rule: AlertRule | null; onSaved: () => void }) {
  const [draft, setDraft] = useState<Draft>(() => draftOf(rule));
  const [groups, setGroups] = useState<ServerGroup[]>([]);
  const [servers, setServers] = useState<Server[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const spec = METRICS[draft.metric];
  const input = inputOf(draft);
  const changes = rule ? changesOf(rule, input) : null;
  const unchanged = changes !== null && Object.keys(changes).length === 0;
  const unscoped = (draft.scope === "group" && !draft.groupId) || (draft.scope === "server" && !draft.serverId);
  // The sentence waits for numbers in the fields it tells.
  const complete =
    !Number.isNaN(input.duration_seconds) && (input.threshold === null || !Number.isNaN(input.threshold));

  const reload = useCallback(
    () =>
      Promise.all([apiFetch<ServerGroup[]>("/server-groups"), apiFetch<Server[]>("/servers")]).then(
        ([g, s]) => {
          setGroups(g);
          setServers(s);
        },
        (e: unknown) => setError(messageFor(e instanceof ApiError ? e.detail : "error")),
      ),
    [],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  function set<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (rule) {
        await apiFetch<AlertRule>(`/alert-rules/${rule.id}`, { method: "PATCH", body: changes });
      } else {
        await apiFetch<AlertRule>("/alert-rules", { method: "POST", body: input });
      }
      onSaved();
    } catch (e) {
      const detail = e instanceof ApiError ? e.detail : "error";
      setError(messageFor(detail));
      if (STALE_DETAILS.includes(detail)) void reload();
    }
    setBusy(false);
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{rule ? `Edit ${rule.name}` : "New alert rule"}</DialogTitle>
        <DialogDescription>A rule fires when its condition holds on a server for its whole duration.</DialogDescription>
      </DialogHeader>
      <form onSubmit={submit} className="grid gap-4">
        {error && <Alert variant="destructive">{error}</Alert>}
        <div className="space-y-2">
          <Label htmlFor="rule-name">Name</Label>
          <Input
            id="rule-name"
            required
            maxLength={80}
            aria-describedby="rule-name-hint"
            value={draft.name}
            onChange={(e) => set("name", e.target.value)}
          />
          <p id="rule-name-hint" className="text-sm text-muted-foreground">
            1 to 80 characters.
          </p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="rule-metric">Watch</Label>
          <Select value={draft.metric} onValueChange={(m) => set("metric", m as AlertMetric)}>
            <SelectTrigger id="rule-metric" aria-label="Watch" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {METRIC_KEYS.map((m) => (
                <SelectItem key={m} value={m}>
                  {METRICS[m].label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {spec.max !== null && (
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label id="rule-comparison">Comparison</Label>
              <RadioGroup
                aria-labelledby="rule-comparison"
                value={draft.comparison}
                onValueChange={(c) => set("comparison", c as Comparison)}
                className="flex h-9 items-center gap-4"
              >
                {COMPARISONS.map(({ value, label }) => (
                  <div key={value} className="flex items-center gap-2">
                    <RadioGroupItem id={`rule-comparison-${value}`} value={value} />
                    <Label htmlFor={`rule-comparison-${value}`} className="font-normal">
                      {label}
                    </Label>
                  </div>
                ))}
              </RadioGroup>
            </div>
            <div className="space-y-2">
              <Label htmlFor="rule-threshold">Limit</Label>
              <div className="flex items-center gap-2">
                <Input
                  id="rule-threshold"
                  type="number"
                  required
                  min={0}
                  max={spec.max}
                  step="any"
                  className="w-28"
                  value={Number.isNaN(draft.threshold) ? "" : draft.threshold}
                  onChange={(e) => set("threshold", e.target.valueAsNumber)}
                />
                <span className="text-sm text-muted-foreground">{spec.unit}</span>
              </div>
            </div>
          </div>
        )}
        <div className="space-y-2">
          <Label htmlFor="rule-minutes">For</Label>
          <div className="flex items-center gap-2">
            <Input
              id="rule-minutes"
              type="number"
              required
              min={0}
              max={1440}
              step={1}
              className="w-28"
              aria-describedby="rule-minutes-hint"
              value={Number.isNaN(draft.minutes) ? "" : draft.minutes}
              onChange={(e) => set("minutes", e.target.valueAsNumber)}
            />
            <span className="text-sm text-muted-foreground">minutes</span>
          </div>
          <p id="rule-minutes-hint" className="text-sm text-muted-foreground">
            0 fires at the first sample
          </p>
        </div>
        <div className="space-y-2">
          <Label id="rule-severity">Severity</Label>
          <RadioGroup
            aria-labelledby="rule-severity"
            value={draft.severity}
            onValueChange={(s) => set("severity", s as Severity)}
            className="flex h-9 items-center gap-4"
          >
            {SEVERITIES.map((s) => (
              <div key={s} className="flex items-center gap-2">
                <RadioGroupItem id={`rule-severity-${s}`} value={s} />
                <Label htmlFor={`rule-severity-${s}`} className="font-normal">
                  {SEVERITY_LABEL[s]}
                </Label>
              </div>
            ))}
          </RadioGroup>
        </div>
        <div className="space-y-2">
          <Label id="rule-scope">Applies to</Label>
          <RadioGroup
            aria-labelledby="rule-scope"
            value={draft.scope}
            onValueChange={(s) => set("scope", s as Scope)}
            className="flex flex-wrap items-center gap-4"
          >
            {SCOPES.map(({ value, label }) => (
              <div key={value} className="flex items-center gap-2">
                <RadioGroupItem id={`rule-scope-${value}`} value={value} />
                <Label htmlFor={`rule-scope-${value}`} className="font-normal">
                  {label}
                </Label>
              </div>
            ))}
          </RadioGroup>
          {draft.scope === "group" && (
            <Select value={draft.groupId} onValueChange={(id) => set("groupId", id)}>
              <SelectTrigger aria-label="Server group" className="w-full">
                <SelectValue placeholder="Choose a server group" />
              </SelectTrigger>
              <SelectContent>
                {groups.map((g) => (
                  <SelectItem key={g.id} value={g.id}>
                    {g.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {draft.scope === "server" && (
            <Select value={draft.serverId} onValueChange={(id) => set("serverId", id)}>
              <SelectTrigger aria-label="Server" className="w-full">
                <SelectValue placeholder="Choose a server" />
              </SelectTrigger>
              <SelectContent>
                {servers.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
        <p aria-live="polite" className="text-sm font-medium">
          {complete && ruleSentence(input)}
        </p>
        <DialogFooter>
          <Button type="submit" disabled={busy || unchanged || unscoped}>
            {rule ? "Save" : "Create rule"}
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}
