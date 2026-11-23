import type { AuthStatus } from "@/lib/auth/gate";

/** The steps of the sign-in. A plain module, so the server page can call `initialStep`. */
export type LoginStep = "password" | "code" | "recovery" | "locked" | "enrol" | "codes";

/** The step a sign-in resumes at, from the session's status. */
export function initialStep(status?: AuthStatus): LoginStep {
  if (status === "mfa_required") return "code";
  if (status === "enrolment_required") return "enrol";
  return "password";
}
