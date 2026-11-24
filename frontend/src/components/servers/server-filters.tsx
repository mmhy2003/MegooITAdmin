"use client";

import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { ServerGroup } from "@/lib/access";
import type { ServerFilters as Filters } from "@/lib/servers";

type Props = {
  groups: ServerGroup[];
  /** The tags in use. */
  tags: string[];
  filters: Filters;
  onChange: (filters: Filters) => void;
};

/** A Select item cannot hold "", so "All groups" has its own value. */
const ALL = "all";

/** Narrows the Servers list to one group and to servers carrying every chosen tag. */
export function ServerFilters({ groups, tags, filters, onChange }: Props) {
  function toggle(tag: string) {
    const chosen = filters.tags.includes(tag) ? filters.tags.filter((t) => t !== tag) : [...filters.tags, tag];
    onChange({ ...filters, tags: chosen });
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select
        value={filters.group ?? ALL}
        onValueChange={(id) => onChange({ ...filters, group: id === ALL ? null : id })}
      >
        <SelectTrigger aria-label="Group" className="w-48">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All groups</SelectItem>
          {groups.map((g) => (
            <SelectItem key={g.id} value={g.id}>
              {g.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {tags.map((tag) => {
        const pressed = filters.tags.includes(tag);
        return (
          <Button
            key={tag}
            size="sm"
            variant={pressed ? "default" : "outline"}
            aria-pressed={pressed}
            onClick={() => toggle(tag)}
          >
            {tag}
          </Button>
        );
      })}
    </div>
  );
}
