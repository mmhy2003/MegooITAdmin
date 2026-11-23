import { cookies } from "next/headers";
import { AppShell } from "@/components/shell/app-shell";
import { requireUser } from "@/lib/auth/server";
import NotFoundContent from "./(app)/not-found";

// Unknown addresses land here, not in a catch-all calling notFound(): the server render cannot catch
// that call, so Next would send its bare error page without the shell or the theme script.
export default async function NotFound() {
  const defaultOpen = (await cookies()).get("sidebar_state")?.value !== "false";
  const user = await requireUser();
  return (
    <AppShell defaultOpen={defaultOpen} user={{ name: user.name, email: user.email }}>
      <NotFoundContent />
    </AppShell>
  );
}
