import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PlaceholderPage } from "@/components/placeholder-page";

describe("PlaceholderPage", () => {
  it("names the page, says what it will hold and that it is not built yet", () => {
    render(<PlaceholderPage href="/servers" />);
    expect(screen.getByRole("heading", { level: 2, name: "Servers" })).toBeInTheDocument();
    expect(screen.getByText("Inventory, groups and tags, with a page per server.")).toBeInTheDocument();
    expect(screen.getByText("Not built yet")).toBeInTheDocument();
  });
});
