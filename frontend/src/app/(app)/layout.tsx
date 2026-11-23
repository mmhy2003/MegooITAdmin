import { cookies } from "next/headers";
import { AppShell } from "@/components/shell/app-shell";
import { requireUser } from "@/lib/auth/server";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  // the sidebar's open state is kept in the cookie SidebarProvider writes
  const defaultOpen = (await cookies()).get("sidebar_state")?.value !== "false";
  const user = await requireUser();
  return (
    <AppShell defaultOpen={defaultOpen} user={{ name: user.name, email: user.email }}>
      {children}
    </AppShell>
  );
}
