import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

describe("shadcn components", () => {
  it("buttons are uppercase, semibold and widely spaced", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toHaveClass("uppercase", "font-semibold", "tracking-wider");
  });

  it("badges are uppercase", () => {
    render(<Badge>New</Badge>);
    expect(screen.getByText("New")).toHaveClass("uppercase");
  });

  it("the sidebar inset is not a main landmark, so the shell owns the only one", () => {
    render(<SidebarProvider><SidebarInset>Content</SidebarInset></SidebarProvider>);
    expect(screen.getByText("Content").tagName).toBe("DIV");
    expect(screen.queryByRole("main")).toBeNull();
  });
});
