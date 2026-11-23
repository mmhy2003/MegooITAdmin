"use client";

import { useState } from "react";
import { CodeStep } from "@/components/auth/code-step";
import { EnrolStep } from "@/components/auth/enrol-step";
import { LockedNotice } from "@/components/auth/locked-notice";
import { PasswordStep } from "@/components/auth/password-step";
import { RecoveryCodes } from "@/components/auth/recovery-codes";
import { RecoveryStep } from "@/components/auth/recovery-step";
import type { AuthStatus } from "@/lib/auth/gate";
import { goTo } from "@/lib/auth/navigate";

export type LoginStep = "password" | "code" | "recovery" | "locked" | "enrol" | "codes";

/** The step a sign-in resumes at, from the session's status. */
export function initialStep(status?: AuthStatus): LoginStep {
  if (status === "mfa_required") return "code";
  if (status === "enrolment_required") return "enrol";
  return "password";
}

type Props = {
  initialStep: LoginStep;
  next: string | null;
};

/** The sign-in: the password, then the code (or the first enrolment), then `next`. */
export function LoginFlow({ initialStep: first, next }: Props) {
  const [step, setStep] = useState<LoginStep>(first);
  const [notice, setNotice] = useState<string | undefined>();
  const [codes, setCodes] = useState<string[]>([]);

  const done = () => goTo(next ?? "/");
  const locked = () => setStep("locked");
  const restart = (text: string) => {
    setNotice(text);
    setStep("password");
  };

  switch (step) {
    case "password":
      return (
        <PasswordStep notice={notice} onDone={(status) => setStep(status === "mfa_required" ? "code" : "enrol")} />
      );
    case "code":
      return (
        <CodeStep onDone={done} onUseRecovery={() => setStep("recovery")} onLocked={locked} onRestart={restart} />
      );
    case "recovery":
      return <RecoveryStep onDone={done} onUseCode={() => setStep("code")} onLocked={locked} onRestart={restart} />;
    case "locked":
      return (
        <LockedNotice
          onBack={() => {
            setNotice(undefined);
            setStep("password");
          }}
        />
      );
    case "enrol":
      return (
        <EnrolStep
          onDone={(given) => {
            if (!given) return done();
            setCodes(given);
            setStep("codes");
          }}
          onRestart={restart}
        />
      );
    case "codes":
      return <RecoveryCodes codes={codes} onContinue={done} />;
  }
}
