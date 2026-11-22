"use client";

import { CircleUser, LogOut, UserCog } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export type AccountUser = { name: string; email: string };

/** The header's account menu; until login exists (MITA-8) the shell passes no user and both items stay disabled. */
export function AccountMenu({ user }: { user: AccountUser | null }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Account">
          <CircleUser aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>
          {user ? (
            <>
              <div>{user.name}</div>
              <div className="text-xs text-muted-foreground">{user.email}</div>
            </>
          ) : (
            "Sign-in is not available yet"
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled>
          <UserCog aria-hidden />
          Profile and security
        </DropdownMenuItem>
        <DropdownMenuItem disabled>
          <LogOut aria-hidden />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
