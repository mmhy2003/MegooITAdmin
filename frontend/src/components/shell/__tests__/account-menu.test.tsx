import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AccountMenu } from "@/components/shell/account-menu";

describe("AccountMenu", () => {
  it("says sign-in is not available yet and disables both items", async () => {
    const user = userEvent.setup();
    render(<AccountMenu user={null} />);
    await user.click(screen.getByRole("button", { name: "Account" }));
    expect(await screen.findByText("Sign-in is not available yet")).toBeInTheDocument();
    for (const name of ["Profile and security", "Sign out"]) {
      expect(screen.getByRole("menuitem", { name })).toHaveAttribute("aria-disabled", "true");
    }
  });
});
