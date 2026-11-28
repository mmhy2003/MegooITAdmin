"use client";

import { BookmarkIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { LogView } from "@/lib/logs/views";

/**
 * The saved views: the person's own and those shared with them, to open one, and what can be done with the view that
 * is open. "Save" shows only while the open view differs and the person may change it; others save as a new view.
 */
export function ViewsMenu({ views, current, changed, onOpen, onSave, onSaveAs, onEdit, onDelete }: {
  views: LogView[];
  current: LogView | null;
  changed: boolean;
  onOpen: (view: LogView) => void;
  onSave: () => void;
  onSaveAs: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const mine = views.filter((v) => v.is_mine);
  const shared = views.filter((v) => !v.is_mine);
  const editable = current !== null && current.can_edit;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" variant="outline">
          <BookmarkIcon />
          Views
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-96 overflow-y-auto">
        {mine.length > 0 && (
          <DropdownMenuGroup>
            <DropdownMenuLabel>My views</DropdownMenuLabel>
            {mine.map((v) => (
              <DropdownMenuItem key={v.id} onSelect={() => onOpen(v)}>{v.name}</DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        )}
        {shared.length > 0 && (
          <DropdownMenuGroup>
            <DropdownMenuLabel>Shared with me</DropdownMenuLabel>
            {shared.map((v) => (
              <DropdownMenuItem key={v.id} onSelect={() => onOpen(v)}>
                <span className="min-w-0 flex-1 truncate">{v.name}</span>{" "}
                <span className="text-xs text-muted-foreground">{v.owner_name}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuGroup>
        )}
        {views.length === 0 && <DropdownMenuLabel className="font-normal">No saved views yet.</DropdownMenuLabel>}
        <DropdownMenuSeparator />
        {editable && changed && <DropdownMenuItem onSelect={onSave}>Save</DropdownMenuItem>}
        <DropdownMenuItem onSelect={onSaveAs}>Save as a new view</DropdownMenuItem>
        {editable && (
          <>
            <DropdownMenuItem onSelect={onEdit}>Rename or share…</DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onSelect={onDelete}>Delete…</DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
