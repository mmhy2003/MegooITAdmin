"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { setTheme, storedTheme } from "@/lib/theme";

/** Flips light and dark; until someone chooses, the page follows the operating system. */
export function ThemeSwitch() {
  // a click in this page counts as a choice even when storage is blocked
  const chosen = useRef(false);

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const onChange = (e: MediaQueryListEvent) => {
      if (!chosen.current && storedTheme() === null) {
        document.documentElement.dataset.theme = e.matches ? "dark" : "light";
      }
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Switch between light and dark"
      onClick={() => {
        chosen.current = true;
        setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
      }}
    >
      {/* both icons are in the server HTML; CSS shows the one for the current theme */}
      <Sun aria-hidden className="dark:hidden" />
      <Moon aria-hidden className="hidden dark:block" />
    </Button>
  );
}
