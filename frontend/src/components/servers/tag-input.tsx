"use client";

import { XIcon } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { addTag, MAX_TAGS } from "@/lib/servers";

type Props = {
  id: string;
  value: string[];
  onChange: (tags: string[]) => void;
  /** The tags already in use, offered while typing. */
  suggestions: string[];
};

/** The chosen tags as chips, and an input that adds one on Enter or a comma; Enter never submits the form. */
export function TagInput({ id, value, onChange, suggestions }: Props) {
  const [text, setText] = useState("");
  const listId = `${id}-suggestions`;

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Enter" && event.key !== ",") return;
    event.preventDefault();
    const next = addTag(value, text);
    if (next !== value) {
      onChange(next);
      setText("");
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {value.map((tag) => (
            <Badge key={tag} variant="secondary" className="pr-0.5">
              {tag}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-4 rounded-full"
                aria-label={`Remove tag ${tag}`}
                onClick={() => onChange(value.filter((t) => t !== tag))}
              >
                <XIcon />
              </Button>
            </Badge>
          ))}
        </div>
      )}
      <Input
        id={id}
        placeholder="Type a tag, then Enter"
        list={listId}
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
        disabled={value.length === MAX_TAGS}
      />
      <datalist id={listId}>
        {suggestions
          .filter((tag) => !value.includes(tag))
          .map((tag) => (
            <option key={tag} value={tag} />
          ))}
      </datalist>
    </div>
  );
}
