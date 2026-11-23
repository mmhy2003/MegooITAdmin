"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

type Props = {
  codes: string[];
  onContinue: () => void;
  continueLabel?: string;
};

/** Shows the new recovery codes once, and goes on only when the person says they saved them. */
export function RecoveryCodes({ codes, onContinue, continueLabel = "Continue" }: Props) {
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copy() {
    await navigator.clipboard.writeText(codes.join("\n"));
    setCopied(true);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">Save your recovery codes</h1>
        </CardTitle>
        <CardDescription>
          Each code signs you in once if you lose your authenticator. They are shown only now.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ol className="grid grid-cols-2 gap-x-6 gap-y-1 rounded-lg border p-4 font-mono text-sm">
          {codes.map((code) => (
            <li key={code}>{code}</li>
          ))}
        </ol>
        <Button type="button" variant="outline" className="w-full" onClick={() => void copy()}>
          {copied ? "Copied" : "Copy codes"}
        </Button>
        <div className="flex items-center gap-2">
          <Checkbox id="codes-saved" checked={saved} onCheckedChange={(v) => setSaved(v === true)} />
          <Label htmlFor="codes-saved">I have saved these codes</Label>
        </div>
        <Button type="button" className="w-full" disabled={!saved} onClick={onContinue}>
          {continueLabel}
        </Button>
      </CardContent>
    </Card>
  );
}
