import { cookies } from "next/headers";
import { AppShell } from "@/components/shell/app-shell";
import NotFoundContent from "./(app)/not-found";

// Unknown addresses land here, not in a catch-all calling notFound(): the server render cannot catch
// that call, so Next would send its bare error page without the shell or the theme script.
export default async function NotFound() {
  const defaultOpen = (await cookies()).get("sidebar_state")?.value !== "false";
  return (
    <AppShell defaultOpen={defaultOpen}>
      <NotFoundContent />
    </AppShell>
  );
}
