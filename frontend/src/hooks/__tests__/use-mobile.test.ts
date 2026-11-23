import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { mockMatchMedia } from "@/__tests__/helpers/match-media";
import { useIsMobile } from "@/hooks/use-mobile";

describe("useIsMobile", () => {
  it("is true below 768 px", () => {
    mockMatchMedia({ width: 767 });
    expect(renderHook(() => useIsMobile()).result.current).toBe(true);
  });

  it("is false from 768 px", () => {
    mockMatchMedia({ width: 768 });
    expect(renderHook(() => useIsMobile()).result.current).toBe(false);
  });
});
