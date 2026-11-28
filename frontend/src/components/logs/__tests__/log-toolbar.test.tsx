import { act, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LogToolbar } from "@/components/logs/log-toolbar";
import { LEVEL_GROUPS, LEVEL_LABELS } from "@/lib/logs/levels";
import { DEFAULT_SETTINGS, type ViewSettings } from "@/lib/logs/sources";

type Props = ComponentProps<typeof LogToolbar>;

function toolbar(props: Partial<Props> = {}) {
  const all: Props = { settings: DEFAULT_SETTINGS, onSettings: vi.fn(), matched: 0, total: 0, ...props };
  return { ...render(<LogToolbar {...all} />), onSettings: all.onSettings as ReturnType<typeof vi.fn> };
}

function field() {
  return screen.getByRole("textbox", { name: "Filter" });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("LogToolbar", () => {
  it("calls onSettings once, 200 ms after the last key", () => {
    vi.useFakeTimers();
    const { onSettings } = toolbar();
    fireEvent.change(field(), { target: { value: "e" } });
    act(() => vi.advanceTimersByTime(150));
    fireEvent.change(field(), { target: { value: "er" } });
    act(() => vi.advanceTimersByTime(150));
    fireEvent.change(field(), { target: { value: "err" } });
    act(() => vi.advanceTimersByTime(199));
    expect(onSettings).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    expect(onSettings).toHaveBeenCalledTimes(1);
    expect(onSettings).toHaveBeenCalledWith({ ...DEFAULT_SETTINGS, q: "err" });
  });

  it("marks an invalid regex and keeps the last valid filter", () => {
    vi.useFakeTimers();
    const { onSettings } = toolbar({ settings: { ...DEFAULT_SETTINGS, regex: true } });
    fireEvent.change(field(), { target: { value: "a(" } });
    act(() => vi.advanceTimersByTime(500));
    expect(field()).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Not a valid regular expression")).toBeInTheDocument();
    expect(onSettings).not.toHaveBeenCalled();
  });

  it("does not mark the same text as invalid while the regex switch is off", () => {
    vi.useFakeTimers();
    const { onSettings } = toolbar();
    fireEvent.change(field(), { target: { value: "a(" } });
    act(() => vi.advanceTimersByTime(200));
    expect(field()).not.toHaveAttribute("aria-invalid", "true");
    expect(onSettings).toHaveBeenCalledWith({ ...DEFAULT_SETTINGS, q: "a(" });
  });

  it("caps the filter at 200 characters", () => {
    toolbar();
    expect(field()).toHaveAttribute("maxLength", "200");
  });

  it("shows the filter it is given, and a new one when the settings change", () => {
    const { rerender } = toolbar({ settings: { ...DEFAULT_SETTINGS, q: "nginx" } });
    expect(field()).toHaveValue("nginx");
    rerender(<LogToolbar settings={{ ...DEFAULT_SETTINGS, q: "sshd" }} onSettings={vi.fn()} matched={0} total={0} />);
    expect(field()).toHaveValue("sshd");
  });

  it("keeps what was typed since when its own filter comes back late", () => {
    vi.useFakeTimers();
    const onSettings = vi.fn();
    const { rerender } = render(<LogToolbar settings={DEFAULT_SETTINGS} onSettings={onSettings} matched={0}
      total={0} />);
    fireEvent.change(field(), { target: { value: "ab" } });
    act(() => vi.advanceTimersByTime(200));
    expect(onSettings).toHaveBeenLastCalledWith({ ...DEFAULT_SETTINGS, q: "ab" });
    fireEvent.change(field(), { target: { value: "abc" } });
    rerender(<LogToolbar settings={{ ...DEFAULT_SETTINGS, q: "ab" }} onSettings={onSettings} matched={0}
      total={0} />);
    expect(field()).toHaveValue("abc");
    act(() => vi.advanceTimersByTime(200));
    expect(onSettings).toHaveBeenLastCalledWith({ ...DEFAULT_SETTINGS, q: "abc" });
  });

  it("takes an outside filter equal to one it handed on before", () => {
    vi.useFakeTimers();
    const onSettings = vi.fn();
    const at = (q: string) => <LogToolbar settings={{ ...DEFAULT_SETTINGS, q }} onSettings={onSettings} matched={0}
      total={0} />;
    const { rerender } = render(at(""));
    fireEvent.change(field(), { target: { value: "ab" } });
    act(() => vi.advanceTimersByTime(200));
    rerender(at("ab"));
    rerender(at(""));
    expect(field()).toHaveValue("");
    rerender(at("ab"));
    expect(field()).toHaveValue("ab");
  });

  it("keeps the field through the echoes of two hand-offs that come back late", () => {
    vi.useFakeTimers();
    const onSettings = vi.fn();
    const at = (q: string) => <LogToolbar settings={{ ...DEFAULT_SETTINGS, q }} onSettings={onSettings} matched={0}
      total={0} />;
    const { rerender } = render(at(""));
    fireEvent.change(field(), { target: { value: "ab" } });
    act(() => vi.advanceTimersByTime(200));
    fireEvent.change(field(), { target: { value: "abc" } });
    act(() => vi.advanceTimersByTime(200));
    fireEvent.change(field(), { target: { value: "abcd" } });
    rerender(at("ab"));
    expect(field()).toHaveValue("abcd");
    rerender(at("abc"));
    expect(field()).toHaveValue("abcd");
    rerender(at(""));
    expect(field()).toHaveValue("");
  });

  it("keeps the regex draft when its own switch comes back late", () => {
    const onSettings = vi.fn();
    const settings = { ...DEFAULT_SETTINGS, q: "a" };
    const { rerender } = render(<LogToolbar settings={settings} onSettings={onSettings} matched={0} total={0} />);
    fireEvent.click(screen.getByRole("button", { name: "Regex" }));
    fireEvent.change(field(), { target: { value: "a(" } });
    rerender(<LogToolbar settings={{ ...settings, regex: true }} onSettings={onSettings} matched={0} total={0} />);
    expect(field()).toHaveValue("a(");
    expect(field()).toHaveAttribute("aria-invalid", "true");
  });

  it("switches the regex on with the text in the field", () => {
    const settings = { ...DEFAULT_SETTINGS, q: "err|warn" };
    const { onSettings } = toolbar({ settings });
    const button = screen.getByRole("button", { name: "Regex" });
    expect(button).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(button);
    expect(onSettings).toHaveBeenCalledWith({ ...settings, regex: true });
  });

  it("switches each level", () => {
    const { onSettings } = toolbar();
    for (const level of LEVEL_GROUPS) {
      const button = screen.getByRole("button", { name: LEVEL_LABELS[level] });
      expect(button).toHaveAttribute("aria-pressed", "true");
      fireEvent.click(button);
      expect(onSettings).toHaveBeenLastCalledWith({
        ...DEFAULT_SETTINGS, levels: LEVEL_GROUPS.filter((l) => l !== level),
      });
    }
  });

  it("switches a level back on in the order of the groups", () => {
    const { onSettings } = toolbar({ settings: { ...DEFAULT_SETTINGS, levels: ["debug", "error"] } });
    const button = screen.getByRole("button", { name: LEVEL_LABELS.warning });
    expect(button).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(button);
    expect(onSettings).toHaveBeenCalledWith({ ...DEFAULT_SETTINGS, levels: ["error", "warning", "debug"] });
  });

  it("switches the layout, wrap and the time zone", () => {
    const merged: ViewSettings = { ...DEFAULT_SETTINGS, layout: "merged", wrap: true, utc: true };
    const { onSettings, unmount } = toolbar();
    expect(screen.getByRole("button", { name: "Side by side" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Merged" }));
    expect(onSettings).toHaveBeenLastCalledWith({ ...DEFAULT_SETTINGS, layout: "merged" });
    fireEvent.click(screen.getByRole("button", { name: "Wrap" }));
    expect(onSettings).toHaveBeenLastCalledWith({ ...DEFAULT_SETTINGS, wrap: true });
    expect(screen.getByRole("button", { name: "Local" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "UTC" }));
    expect(onSettings).toHaveBeenLastCalledWith({ ...DEFAULT_SETTINGS, utc: true });
    unmount();

    const other = toolbar({ settings: merged });
    expect(screen.getByRole("button", { name: "Merged" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Wrap" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Side by side" }));
    expect(other.onSettings).toHaveBeenLastCalledWith({ ...merged, layout: "side_by_side" });
    fireEvent.click(screen.getByRole("button", { name: "Local" }));
    expect(other.onSettings).toHaveBeenLastCalledWith({ ...merged, utc: false });
  });

  it("counts the matching lines only while a filter or a level is on", () => {
    const { rerender } = toolbar({ matched: 212, total: 4203 });
    expect(screen.queryByText(/lines match/)).not.toBeInTheDocument();
    const onSettings = vi.fn();
    rerender(<LogToolbar settings={{ ...DEFAULT_SETTINGS, q: "err" }} onSettings={onSettings} matched={212}
      total={4203} />);
    expect(screen.getByText("212 of 4,203 lines match")).toBeInTheDocument();
    rerender(<LogToolbar settings={{ ...DEFAULT_SETTINGS, levels: ["error"] }} onSettings={onSettings} matched={212}
      total={4203} />);
    expect(screen.getByText("212 of 4,203 lines match")).toBeInTheDocument();
  });

  it("offers Add source only with onAddSource", () => {
    const { unmount } = toolbar();
    expect(screen.queryByRole("button", { name: "Add source" })).not.toBeInTheDocument();
    unmount();
    const onAddSource = vi.fn();
    toolbar({ onAddSource });
    fireEvent.click(screen.getByRole("button", { name: "Add source" }));
    expect(onAddSource).toHaveBeenCalledTimes(1);
  });

  it("renders extra", () => {
    toolbar({ extra: <span>Views</span> });
    expect(screen.getByText("Views")).toBeInTheDocument();
  });
});
