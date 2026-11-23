"use client";

import { usePathname } from "next/navigation";
import { AccountMenu, type AccountUser } from "@/components/shell/account-menu";
import { SearchPlaceholder } from "@/components/shell/search-placeholder";
import { ThemeSwitch } from "@/components/shell/theme-switch";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { pageTitle } from "@/lib/navigation";

/** The bar above every page: the sidebar button, the page title, search, the theme and the account. */
export function SiteHeader({ user }: { user: AccountUser }) {
  const title = pageTitle(usePathname());

  return (
    <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="mx-1 h-5" />
      <h1 className="truncate text-base font-semibold">{title}</h1>
      <div className="ml-auto flex items-center gap-1">
        <SearchPlaceholder />
        <ThemeSwitch />
        <AccountMenu user={user} />
      </div>
    </header>
  );
}
