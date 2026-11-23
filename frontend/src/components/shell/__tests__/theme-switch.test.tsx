import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { mockMatchMedia } from "@/__tests__/helpers/match-media";
import { ThemeSwitch } from "@/components/shell/theme-switch";

const theme = () => document.documentElement.dataset.theme;
const button = () => screen.getByRole("button", { name: "Switch between light and dark" });

describe("ThemeSwitch", () => {
  it("switches from light to dark and stores the choice", async () => {
    const user = userEvent.setup();
    document.documentElement.dataset.theme = "light";
    render(<ThemeSwitch />);
    await user.click(button());
    expect(theme()).toBe("dark");
    expect(localStorage.getItem("megoo-theme")).toBe("dark");
    await user.click(button());
    expect(theme()).toBe("light");
  });

  it("still switches when storage is blocked", async () => {
    const user = userEvent.setup();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    document.documentElement.dataset.theme = "light";
    render(<ThemeSwitch />);
    await user.click(button());
    expect(theme()).toBe("dark");
  });

  it("follows the operating system while nothing is stored", () => {
    const os = mockMatchMedia();
    document.documentElement.dataset.theme = "light";
    render(<ThemeSwitch />);
    act(() => os.setDark(true));
    expect(theme()).toBe("dark");
    act(() => os.setDark(false));
    expect(theme()).toBe("light");
  });

  it("stops following the system after a click", async () => {
    const user = userEvent.setup();
    const os = mockMatchMedia();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    document.documentElement.dataset.theme = "light";
    render(<ThemeSwitch />);
    await user.click(button());
    expect(theme()).toBe("dark");
    act(() => os.setDark(false));
    expect(theme()).toBe("dark");
  });

  it("keeps a stored choice when the system changes", () => {
    const os = mockMatchMedia();
    localStorage.setItem("megoo-theme", "light");
    document.documentElement.dataset.theme = "light";
    render(<ThemeSwitch />);
    act(() => os.setDark(true));
    expect(theme()).toBe("light");
  });
});
