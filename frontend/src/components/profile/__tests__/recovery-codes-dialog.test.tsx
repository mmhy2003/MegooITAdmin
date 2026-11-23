import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RecoveryCodesDialog } from "@/components/profile/recovery-codes-dialog";
import { ApiError, apiFetch } from "@/lib/api";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), apiFetch: vi.fn() }));
vi.mock("@/lib/auth/navigate");

const CODES = Array.from({ length: 10 }, (_, i) => `AAAA-BBBB-CCCC-000${i}`);

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

function renderDialog() {
  const props = { onOpenChange: vi.fn(), onCreated: vi.fn() };
  render(<RecoveryCodesDialog open {...props} />);
  return props;
}

async function create(code: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Code"), code);
  await user.click(screen.getByRole("button", { name: "Create codes" }));
  return user;
}

describe("RecoveryCodesDialog", () => {
  it("posts the code and shows the 10 new codes", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ recovery_codes: CODES });
    renderDialog();
    expect(screen.getByRole("dialog", { name: "New recovery codes" })).toBeInTheDocument();
    expect(screen.getByText("Enter a code from your authenticator. The old codes stop working.")).toBeInTheDocument();

    await create("123456");

    expect(apiFetch).toHaveBeenCalledWith("/auth/recovery-codes", { method: "POST", body: { code: "123456" } });
    for (const code of CODES) expect(await screen.findByText(code)).toBeInTheDocument();
  });

  it("keeps Done disabled until the codes are saved, then calls onCreated and closes", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ recovery_codes: CODES });
    const { onCreated, onOpenChange } = renderDialog();

    const user = await create("123456");
    const done = await screen.findByRole("button", { name: "Done" });
    expect(done).toBeDisabled();

    await user.click(screen.getByLabelText("I have saved these codes"));
    await user.click(done);

    expect(onCreated).toHaveBeenCalledOnce();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("says when the code is wrong", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new ApiError(401, "wrong_code"));
    const { onCreated } = renderDialog();

    await create("000000");

    expect(await screen.findByRole("alert")).toHaveTextContent("That code is not right.");
    expect(screen.queryByText("Save your recovery codes")).not.toBeInTheDocument();
    expect(onCreated).not.toHaveBeenCalled();
  });
});
