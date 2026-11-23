"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Wordmark } from "@/components/shell/wordmark";
import {
  Sidebar, SidebarContent, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarHeader,
  SidebarMenu, SidebarMenuButton, SidebarMenuItem, useSidebar,
} from "@/components/ui/sidebar";
import { isActive, NAV_GROUPS } from "@/lib/navigation";
import { cn } from "@/lib/utils";

// the current page: cyan text and a glowing bar on its left edge
const ACTIVE =
  "relative data-[active=true]:font-semibold data-[active=true]:text-cyan-ink data-[active=true]:before:absolute data-[active=true]:before:inset-y-1 data-[active=true]:before:left-0 data-[active=true]:before:w-0.5 data-[active=true]:before:rounded-full data-[active=true]:before:bg-cyan data-[active=true]:before:shadow-(--glow-cyan)";

export function AppSidebar() {
  const pathname = usePathname();
  const { isMobile, setOpenMobile } = useSidebar();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <Wordmark />
      </SidebarHeader>
      <SidebarContent>
        <nav aria-label="Main" className="flex flex-col">
          {NAV_GROUPS.map((group, index) => (
            <SidebarGroup
              key={group.label}
              className={cn(index > 0 && "group-data-[collapsible=icon]:border-t group-data-[collapsible=icon]:border-sidebar-border")}
            >
              <SidebarGroupLabel className="text-[11px] uppercase tracking-wider">{group.label}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {group.items.map((item) => {
                    const active = isActive(pathname, item.href);
                    return (
                      <SidebarMenuItem key={item.href}>
                        <SidebarMenuButton asChild isActive={active} tooltip={item.title} className={ACTIVE}>
                          <Link
                            href={item.href}
                            aria-current={active ? "page" : undefined}
                            onClick={() => {
                              if (isMobile) setOpenMobile(false);
                            }}
                          >
                            <item.icon aria-hidden />
                            <span>{item.title}</span>
                          </Link>
                        </SidebarMenuButton>
                      </SidebarMenuItem>
                    );
                  })}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}
        </nav>
      </SidebarContent>
    </Sidebar>
  );
}
