import { cookies } from "next/headers";
import { AppShell } from "@/components/shell/app-shell";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  // the sidebar's open state is kept in the cookie SidebarProvider writes
  const defaultOpen = (await cookies()).get("sidebar_state")?.value !== "false";
  return <AppShell defaultOpen={defaultOpen}>{children}</AppShell>;
}
