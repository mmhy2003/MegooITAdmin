"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Ref = (element: Element | null) => void;

function changed(visible: Set<string>, id: string, shown: boolean): Set<string> {
  if (visible.has(id) === shown) return visible;
  const next = new Set(visible);
  if (shown) next.add(id);
  else next.delete(id);
  return next;
}

/**
 * Which tracked elements are inside the viewport, with a 200px margin, through one IntersectionObserver. Pass
 * `track(id)` as an element's ref. Without IntersectionObserver every tracked id counts as on screen.
 */
export function useOnScreen(): { track: (id: string) => Ref; onScreen: string[] } {
  const [visible, setVisible] = useState<Set<string>>(() => new Set());
  const elements = useRef(new Map<string, Element>());
  const refs = useRef(new Map<string, Ref>());
  const observer = useRef<IntersectionObserver | null>(null);

  const observe = useCallback((): IntersectionObserver | null => {
    if (typeof IntersectionObserver === "undefined") return null;
    observer.current ??= new IntersectionObserver(
      (entries) => {
        setVisible((current) =>
          entries.reduce((next, entry) => {
            const id = entry.target.getAttribute("data-server-id");
            return id === null ? next : changed(next, id, entry.isIntersecting);
          }, current),
        );
      },
      { rootMargin: "200px" },
    );
    return observer.current;
  }, []);

  const track = useCallback(
    (id: string): Ref => {
      let ref = refs.current.get(id);
      if (ref === undefined) {
        ref = (element: Element | null) => {
          const previous = elements.current.get(id);
          if (previous !== undefined) {
            observer.current?.unobserve(previous);
            elements.current.delete(id);
            setVisible((current) => changed(current, id, false));
          }
          if (element === null) return;
          if (!element.hasAttribute("data-server-id")) element.setAttribute("data-server-id", id);
          elements.current.set(id, element);
          const io = observe();
          if (io === null) setVisible((current) => changed(current, id, true));
          else io.observe(element);
        };
        refs.current.set(id, ref);
      }
      return ref;
    },
    [observe],
  );

  useEffect(
    () => () => {
      observer.current?.disconnect();
      observer.current = null;
    },
    [],
  );

  const onScreen = useMemo(() => [...visible].sort(), [visible]);
  return { track, onScreen };
}
