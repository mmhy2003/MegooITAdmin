"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** Shown instead of the code steps after too many failed attempts. */
export function LockedNotice({ onBack }: { onBack: () => void }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h1 className="text-xl">Account locked</h1>
        </CardTitle>
        <CardDescription>
          Too many failed attempts. Try again in 15 minutes, or ask the host&apos;s administrator to run make
          reset-password.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button type="button" className="w-full" onClick={onBack}>
          Back to sign-in
        </Button>
      </CardContent>
    </Card>
  );
}
