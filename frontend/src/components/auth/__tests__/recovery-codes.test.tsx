import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RecoveryCodes } from "@/components/auth/recovery-codes";

const CODES = Array.from({ length: 10 }, (_, i) => `AAAA-BBBB-CCCC-000${i}`);

describe("RecoveryCodes", () => {
  it("shows every code", () => {
    render(<RecoveryCodes codes={CODES} onContinue={vi.fn()} />);

    expect(screen.getByText("Save your recovery codes")).toBeInTheDocument();
    expect(
      screen.getByText("Each code signs you in once if you lose your authenticator. They are shown only now."),
    ).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual(CODES);
  });

  it("continues only once the codes are saved", async () => {
    const user = userEvent.setup();
    const onContinue = vi.fn();
    render(<RecoveryCodes codes={CODES} onContinue={onContinue} />);
    const button = screen.getByRole("button", { name: "Continue" });
    expect(button).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: "I have saved these codes" }));
    expect(button).toBeEnabled();
    await user.click(button);

    expect(onContinue).toHaveBeenCalled();
  });

  it("copies the codes, one per line", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<RecoveryCodes codes={CODES} onContinue={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Copy codes" }));

    expect(writeText).toHaveBeenCalledWith(CODES.join("\n"));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("uses the given label for the continue button", () => {
    render(<RecoveryCodes codes={CODES} onContinue={vi.fn()} continueLabel="Done" />);

    expect(screen.getByRole("button", { name: "Done" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Continue" })).not.toBeInTheDocument();
  });
});
