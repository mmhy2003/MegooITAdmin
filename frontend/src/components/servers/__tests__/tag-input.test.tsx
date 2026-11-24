import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { TagInput } from "@/components/servers/tag-input";

function Harness({ initial = [], suggestions = [] }: { initial?: string[]; suggestions?: string[] }) {
  const [tags, setTags] = useState<string[]>(initial);
  return <TagInput id="tags" value={tags} onChange={setTags} suggestions={suggestions} />;
}

function setup(props: { initial?: string[]; suggestions?: string[] } = {}) {
  render(<Harness {...props} />);
  return { user: userEvent.setup(), input: screen.getByPlaceholderText("Type a tag, then Enter") };
}

function chips() {
  return screen.queryAllByText(/^[a-z0-9][a-z0-9._-]*$/).map((el) => el.textContent);
}

describe("TagInput", () => {
  it("adds a typed tag on Enter, lowercased, and clears the text", async () => {
    const { user, input } = setup();
    await user.type(input, "Web{Enter}");
    expect(chips()).toEqual(["web"]);
    expect(input).toHaveValue("");
  });

  it("adds a typed tag on a comma", async () => {
    const { user, input } = setup();
    await user.type(input, "db,");
    expect(chips()).toEqual(["db"]);
    expect(input).toHaveValue("");
  });

  it("removes a tag with its remove button", async () => {
    const { user } = setup({ initial: ["web", "db"] });
    await user.click(screen.getByRole("button", { name: "Remove tag web" }));
    expect(chips()).toEqual(["db"]);
  });

  it("ignores a duplicate", async () => {
    const { user, input } = setup({ initial: ["web"] });
    await user.type(input, "WEB{Enter}");
    expect(chips()).toEqual(["web"]);
    expect(input).toHaveValue("WEB");
  });

  it("ignores an invalid tag and keeps the text", async () => {
    const { user, input } = setup();
    await user.type(input, "-bad{Enter}");
    expect(chips()).toEqual([]);
    expect(input).toHaveValue("-bad");
  });

  it("never submits the surrounding form on Enter", async () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <Harness />
      </form>,
    );
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("Type a tag, then Enter"), "web{Enter}");
    await user.type(screen.getByPlaceholderText("Type a tag, then Enter"), "{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("suggests only the tags not chosen yet", () => {
    const { input } = setup({ initial: ["web"], suggestions: ["db", "web", "edge"] });
    expect(input).toHaveAttribute("list", "tags-suggestions");
    const options = document.querySelectorAll("datalist#tags-suggestions option");
    expect([...options].map((o) => o.getAttribute("value"))).toEqual(["db", "edge"]);
  });

  it("is disabled once the most tags are chosen", () => {
    const { input } = setup({ initial: Array.from({ length: 20 }, (_, i) => `t${i}`) });
    expect(input).toBeDisabled();
  });
});
