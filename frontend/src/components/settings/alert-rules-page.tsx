"use client";

import { Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { SeverityBadge } from "@/components/alerts/severity-badge";
import { AlertRuleDialog } from "@/components/settings/alert-rule-dialog";
import { DeleteRuleDialog } from "@/components/settings/delete-rule-dialog";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { type AlertRule, ruleSentence } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";
import { messageFor } from "@/lib/auth/messages";

function scopeOf(rule: AlertRule): string {
  return rule.server_name ?? rule.server_group_name ?? "All servers";
}

/** The Alert rules tab of Settings: every rule, what it watches and where, how many servers it fires on, and the Owner's changes. */
export function AlertRulesPage() {
  const [rules, setRules] = useState<AlertRule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // `undefined` is closed, `null` is a new rule.
  const [editing, setEditing] = useState<AlertRule | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<AlertRule | null>(null);
  // The rules whose switch is being sent: held so a second click cannot overtake the first.
  const [switching, setSwitching] = useState<ReadonlySet<string>>(new Set());

  const reload = useCallback(
    () =>
      apiFetch<AlertRule[]>("/alert-rules").then(
        (list) => {
          setRules(list);
          setError(null);
        },
        (e: unknown) => setError(e instanceof ApiError ? e.detail : "error"),
      ),
    [],
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  async function toggle(rule: AlertRule, enabled: boolean) {
    setSwitching((ids) => new Set(ids).add(rule.id));
    try {
      await apiFetch<AlertRule>(`/alert-rules/${rule.id}`, { method: "PATCH", body: { enabled } });
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "error");
    }
    setSwitching((ids) => {
      const rest = new Set(ids);
      rest.delete(rule.id);
      return rest;
    });
  }

  function saved() {
    setEditing(undefined);
    void reload();
  }

  function deleted() {
    setDeleting(null);
    void reload();
  }

  return (
    <div className="space-y-6">
      {error && <Alert variant="destructive">{messageFor(error)}</Alert>}
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Alert rules</h2>
          </CardTitle>
          <CardAction>
            <Button onClick={() => setEditing(null)}>
              <Plus aria-hidden />
              New rule
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          {rules?.length === 0 && <p className="text-sm text-muted-foreground">No alert rules. Nothing is watched.</p>}
          {rules && rules.length > 0 && (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Rule</TableHead>
                    <TableHead>Applies to</TableHead>
                    <TableHead>Severity</TableHead>
                    <TableHead>Firing</TableHead>
                    <TableHead>
                      <span className="sr-only">Enabled</span>
                    </TableHead>
                    <TableHead>
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rules.map((rule) => (
                    <TableRow key={rule.id}>
                      <TableCell>
                        <div className="font-medium">{rule.name}</div>
                        <div className="text-muted-foreground">{ruleSentence(rule)}</div>
                      </TableCell>
                      <TableCell>{scopeOf(rule)}</TableCell>
                      <TableCell>
                        <SeverityBadge severity={rule.severity} />
                      </TableCell>
                      <TableCell>
                        Firing on {rule.firing_count} {rule.firing_count === 1 ? "server" : "servers"}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Switch
                            id={`rule-enabled-${rule.id}`}
                            checked={rule.enabled}
                            disabled={switching.has(rule.id)}
                            onCheckedChange={(enabled) => void toggle(rule, enabled)}
                          />
                          <Label htmlFor={`rule-enabled-${rule.id}`}>Enabled</Label>
                        </div>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Edit ${rule.name}`}
                          onClick={() => setEditing(rule)}
                        >
                          <Pencil aria-hidden />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Delete ${rule.name}`}
                          onClick={() => setDeleting(rule)}
                        >
                          <Trash2 aria-hidden />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
      <AlertRuleDialog
        rule={editing}
        open={editing !== undefined}
        onOpenChange={(open) => !open && setEditing(undefined)}
        onSaved={saved}
      />
      <DeleteRuleDialog
        rule={deleting}
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        onDeleted={deleted}
      />
    </div>
  );
}
