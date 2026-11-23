import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { AccessForm } from "@/components/settings/access-form";
import { type AccessValue, PERMISSION_LABELS, PERMISSIONS, type ServerGroup } from "@/lib/access";

const GROUPS: ServerGroup[] = [
  { id: "g-staging", name: "staging", description: null, created_at: "2026-11-01T00:00:00Z", member_count: 0 },
  { id: "g-production", name: "production", description: null, created_at: "2026-11-01T00:00:00Z", member_count: 0 },
];

const NOBODY: AccessValue = { platform_role: null, grants: [] };

/** Keeps the value in state, as a dialog does, and reports every change to `onChange`. */
function Controlled({ initial = NOBODY, groups = GROUPS, onChange = vi.fn() }: {
  initial?: AccessValue;
  groups?: ServerGroup[];
  onChange?: (v: AccessValue) => void;
}) {
  const [value, setValue] = useState(initial);
  return (
    <AccessForm
      value={value}
      groups={groups}
      onChange={(v) => {
        setValue(v);
        onChange(v);
      }}
    />
  );
}

function box(permission: (typeof PERMISSIONS)[number], group: string) {
  return screen.getByRole("checkbox", { name: `${PERMISSION_LABELS[permission]} in ${group}` });
}

async function chooseRole(group: string, role: "No access" | "Admin" | "Operator") {
  const user = userEvent.setup();
  await user.click(screen.getByRole("combobox", { name: `Role in ${group}` }));
  await user.click(await screen.findByRole("option", { name: role }));
}

describe("AccessForm", () => {
  it("choosing Admin ticks all seven switches", async () => {
    const onChange = vi.fn();
    render(<Controlled onChange={onChange} />);

    await chooseRole("staging", "Admin");

    for (const p of PERMISSIONS) {
      expect(box(p, "staging")).toBeChecked();
      expect(box(p, "staging")).toBeEnabled();
      expect(box(p, "production")).not.toBeChecked();
    }
    expect(onChange).toHaveBeenLastCalledWith({
      platform_role: null,
      grants: [{ group_id: "g-staging", role: "admin", ...Object.fromEntries(PERMISSIONS.map((p) => [p, true])) }],
    });
  });

  it("choosing Operator ticks its five and disables Manage playbooks", async () => {
    render(<Controlled />);

    await chooseRole("production", "Operator");

    for (const p of ["connect_ssh", "connect_rdp", "view_logs", "view_processes", "run_playbooks"] as const) {
      expect(box(p, "production")).toBeChecked();
    }
    expect(box("manage_processes", "production")).not.toBeChecked();
    expect(box("manage_processes", "production")).toBeEnabled();
    expect(box("manage_playbooks", "production")).not.toBeChecked();
    expect(box("manage_playbooks", "production")).toBeDisabled();
  });

  it("No access clears and disables the row", async () => {
    const onChange = vi.fn();
    render(<Controlled onChange={onChange} />);
    await chooseRole("staging", "Admin");

    await chooseRole("staging", "No access");

    for (const p of PERMISSIONS) {
      expect(box(p, "staging")).not.toBeChecked();
      expect(box(p, "staging")).toBeDisabled();
    }
    expect(onChange).toHaveBeenLastCalledWith({ platform_role: null, grants: [] });
  });

  it("Auditor and Owner hide the matrix, and By server group brings the rows back", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Controlled onChange={onChange} />);
    await chooseRole("staging", "Operator");

    await user.click(screen.getByRole("radio", { name: /Auditor/ }));
    expect(screen.queryByRole("combobox", { name: "Role in staging" })).not.toBeInTheDocument();
    expect(screen.getByText(/Holds none of the grants\./)).toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith({ platform_role: "auditor", grants: [] });

    await user.click(screen.getByRole("radio", { name: /Owner/ }));
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByText(/Runs the platform: people, settings and every group\./)).toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith({ platform_role: "owner", grants: [] });

    await user.click(screen.getByRole("radio", { name: /By server group/ }));
    expect(screen.getByRole("combobox", { name: "Role in staging" })).toHaveTextContent("Operator");
    expect(box("connect_ssh", "staging")).toBeChecked();
    expect(onChange).toHaveBeenLastCalledWith({
      platform_role: null,
      grants: [expect.objectContaining({ group_id: "g-staging", role: "operator", connect_ssh: true })],
    });
  });

  it("a switch can be turned off after choosing a role", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Controlled onChange={onChange} />);
    await chooseRole("staging", "Admin");

    await user.click(box("view_logs", "staging"));

    expect(box("view_logs", "staging")).not.toBeChecked();
    expect(box("connect_ssh", "staging")).toBeChecked();
    expect(onChange).toHaveBeenLastCalledWith({
      platform_role: null,
      grants: [expect.objectContaining({ group_id: "g-staging", role: "admin", view_logs: false, connect_ssh: true })],
    });
  });

  it("it says only the connect switches are checked for now", () => {
    render(<Controlled />);

    expect(
      screen.getByText(
        "Only Connect SSH and Connect RDP are checked by the app for now. The other switches are saved for the features that come later.",
      ),
    ).toBeInTheDocument();
  });

  it("without groups it points to the Server groups tab", () => {
    render(<Controlled groups={[]} />);

    expect(screen.getByText(/No server groups yet\. Create one on the/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Server groups/ })).toHaveAttribute("href", "/settings/groups");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
