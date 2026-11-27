import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { EmailDialog } from "@/components/settings/email-dialog";
import type { EmailSettings } from "@/lib/alerts";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const NOT_SET_UP: EmailSettings = {
  enabled: false,
  host: null,
  port: 587,
  security: "starttls",
  username: null,
  password_set: false,
  from_name: "MegooITAdmin",
  from_address: null,
  extra_addresses: [],
  min_severity: "warning",
  last_delivery: null,
};
const SET_UP: EmailSettings = {
  ...NOT_SET_UP,
  enabled: true,
  host: "smtp.example.com",
  port: 465,
  security: "tls",
  username: "alerts",
  password_set: true,
  from_address: "alerts@example.com",
  extra_addresses: ["oncall@example.com", "noc@example.com"],
  min_severity: "critical",
};
const SAVED_BODY = {
  enabled: true,
  host: "smtp.example.com",
  port: 465,
  security: "tls",
  username: "alerts",
  from_name: "MegooITAdmin",
  from_address: "alerts@example.com",
  extra_addresses: ["oncall@example.com", "noc@example.com"],
  min_severity: "critical",
};

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
  vi.mocked(apiFetch).mockResolvedValue(SET_UP);
});

function renderDialog(email: EmailSettings) {
  const onSaved = vi.fn();
  render(<EmailDialog email={email} open onOpenChange={vi.fn()} onSaved={onSaved} />);
  return { onSaved, user: userEvent.setup() };
}

describe("EmailDialog", () => {
  it("shows the saved settings but never the password", () => {
    renderDialog(SET_UP);

    expect(screen.getByRole("heading", { name: "Email" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Enabled" })).toBeChecked();
    expect(screen.getByRole("textbox", { name: "Host" })).toHaveValue("smtp.example.com");
    expect(screen.getByRole("spinbutton", { name: "Port" })).toHaveValue(465);
    expect(screen.getByRole("radio", { name: "TLS" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "STARTTLS" })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: "None" })).not.toBeChecked();
    expect(screen.getByRole("textbox", { name: "User name" })).toHaveValue("alerts");
    const password = screen.getByLabelText("Password");
    expect(password).toHaveValue("");
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("placeholder", "Saved, type to replace");
    expect(screen.getByRole("checkbox", { name: "Remove the saved password" })).not.toBeChecked();
    expect(screen.getByRole("textbox", { name: "From name" })).toHaveValue("MegooITAdmin");
    expect(screen.getByRole("textbox", { name: "From address" })).toHaveValue("alerts@example.com");
    const extra = screen.getByRole("textbox", { name: "Extra addresses" });
    expect(extra).toHaveValue("oncall@example.com\nnoc@example.com");
    expect(extra).toHaveAccessibleDescription(
      "One per line, 20 at most. They get every alert the filter lets through.",
    );
    expect(screen.getByRole("radio", { name: "Critical only" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Warning and Critical" })).not.toBeChecked();
  });

  it("has no saved password to keep or remove before setup", () => {
    renderDialog(NOT_SET_UP);

    expect(screen.getByRole("switch", { name: "Enabled" })).not.toBeChecked();
    expect(screen.getByLabelText("Password")).not.toHaveAttribute("placeholder");
    expect(screen.queryByRole("checkbox", { name: "Remove the saved password" })).not.toBeInTheDocument();
  });

  it("saves without the password when it was not typed", async () => {
    const { user, onSaved } = renderDialog(SET_UP);

    await user.type(screen.getByRole("textbox", { name: "Extra addresses" }), "\n\n ops@example.com \n");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/notifications/email", {
      method: "PUT",
      body: { ...SAVED_BODY, extra_addresses: [...SAVED_BODY.extra_addresses, "ops@example.com"] },
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("sends a typed password", async () => {
    const { user } = renderDialog(SET_UP);

    await user.type(screen.getByLabelText("Password"), "s3cret pass");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/notifications/email", {
      method: "PUT",
      body: { ...SAVED_BODY, password: "s3cret pass" },
    });
  });

  it("removes the saved password", async () => {
    const { user } = renderDialog(SET_UP);

    await user.click(screen.getByRole("checkbox", { name: "Remove the saved password" }));
    expect(screen.getByLabelText("Password")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/notifications/email", {
      method: "PUT",
      body: { ...SAVED_BODY, password: "" },
    });
  });

  it("sets up email from the empty settings", async () => {
    const { user } = renderDialog(NOT_SET_UP);

    await user.click(screen.getByRole("switch", { name: "Enabled" }));
    await user.type(screen.getByRole("textbox", { name: "Host" }), "mail.example.org");
    await user.clear(screen.getByRole("spinbutton", { name: "Port" }));
    await user.type(screen.getByRole("spinbutton", { name: "Port" }), "25");
    await user.click(screen.getByRole("radio", { name: "None" }));
    await user.type(screen.getByRole("textbox", { name: "From address" }), "alerts@example.org");
    await user.click(screen.getByRole("radio", { name: "Critical only" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(apiFetch).toHaveBeenCalledWith("/notifications/email", {
      method: "PUT",
      body: {
        enabled: true,
        host: "mail.example.org",
        port: 25,
        security: "none",
        username: "",
        from_name: "MegooITAdmin",
        from_address: "alerts@example.org",
        extra_addresses: [],
        min_severity: "critical",
      },
    });
  });

  it("refuses more than 20 extra addresses", async () => {
    const { user } = renderDialog(NOT_SET_UP);

    const lines = Array.from({ length: 21 }, (_, i) => `a${i}@example.com`).join("\n");
    await user.click(screen.getByRole("textbox", { name: "Extra addresses" }));
    await user.paste(lines);

    expect(screen.getByRole("textbox", { name: "Extra addresses" })).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("shows a refused save", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(422, "invalid"));
    const { user, onSaved } = renderDialog(SET_UP);

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Check the fields and try again.")).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
  });
});
