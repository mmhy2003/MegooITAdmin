import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FakeIntersectionObserver, installIntersectionObserver } from "@/__tests__/helpers/intersection-observer";
import { useOnScreen } from "@/hooks/use-on-screen";

function Probe() {
  const { track, onScreen } = useOnScreen();
  return (
    <>
      {["a", "b", "c"].map((id) => (
        <div key={id} ref={track(id)} data-server-id={id} />
      ))}
      <output data-testid="on-screen">{onScreen.join(",")}</output>
    </>
  );
}

function onScreen(): string {
  return screen.getByTestId("on-screen").textContent ?? "";
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useOnScreen", () => {
  it("lists the tracked ids inside the viewport, sorted", () => {
    const observer = installIntersectionObserver();
    render(<Probe />);
    act(() => observer.show(["b", "a"]));
    expect(onScreen()).toBe("a,b");
    act(() => observer.show(["c"]));
    expect(onScreen()).toBe("c");
  });

  it("uses one observer with a 200px margin", () => {
    installIntersectionObserver();
    render(<Probe />);
    expect(FakeIntersectionObserver.instances).toHaveLength(1);
    expect(FakeIntersectionObserver.instances[0].options?.rootMargin).toBe("200px");
    expect(FakeIntersectionObserver.instances[0].observed.size).toBe(3);
  });

  it("counts every tracked id without IntersectionObserver", () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    render(<Probe />);
    expect(onScreen()).toBe("a,b,c");
  });
});
