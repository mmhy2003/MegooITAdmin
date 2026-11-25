# MITA-240 plan: the Servers pages show the monitoring state and the sample interval

## Goal

The Servers list and each server's page show whether the collector reaches the server (Reachable, Unreachable, Not monitored, Not checked yet) and why not. Register and Edit set a Linux server's sample interval. Both pages re-read every 15 seconds without keeping an idle session alive.

## Architecture

The frontend reads `metrics_interval_seconds` and `monitoring`, which the server API has returned since MITA-26. It shows them in a new `MonitoringBadge` and a new `MonitoringCard`, and re-reads through a new `useRefresh` hook. Re-reads call `apiFetch(path, { background: true })`, which sends `X-Megoo-Background: 1`. On the backend, `current_session` sees that header and calls `lookup_session(..., touch=False)`, so `last_seen_at` stays where it was. The header can only shorten a session. There is no migration and no change to the server API.

## File map

| File | Change | Responsibility |
|---|---|---|
| `frontend/src/lib/servers.ts` | modify | `MonitoringState`, `MonitoringReason`, `Monitoring`, `DEFAULT_INTERVAL`; new fields on `Server`, `ServerDraft` (`interval`) and `ServerBody` (`metrics_interval_seconds`); `draftOf`, `bodyOf` and `changesOf` handle the interval |
| `frontend/src/lib/api.ts` | modify | the `background?: boolean` option, which adds `x-megoo-background: 1` |
| `frontend/src/lib/auth/messages.ts` | modify | `MONITORING_REASONS`, `NOT_CHECKED`, `monitoringText(reason)` |
| `frontend/src/hooks/use-refresh.ts` | new | `useRefresh(refresh, active)` and `REFRESH_EVERY_MS = 15_000` |
| `frontend/src/components/servers/monitoring-badge.tsx` | new | the four-state badge |
| `frontend/src/components/servers/field.tsx` | new | the `Field` (dt/dd) row, moved out of `server-page.tsx` so the card can use it too |
| `frontend/src/components/servers/monitoring-card.tsx` | new | the Monitoring card |
| `frontend/src/components/servers/servers-page.tsx` | modify | the Status column and the background re-read |
| `frontend/src/components/servers/server-page.tsx` | modify | the badge after the name, the Monitoring card and the background re-read |
| `frontend/src/components/servers/server-dialog.tsx` | modify | the Sample interval field (Linux only) |
| `backend/app/auth/sessions.py` | modify | `BACKGROUND_HEADER`; `lookup_session(..., *, touch=True)` |
| `backend/app/auth/deps.py` | modify | `current_session` passes `touch=False` when the header is `1` |
| `README.md` | modify | the Servers section |
| Tests | new or modify | `lib/__tests__/servers.test.ts`, `lib/__tests__/api.test.ts`, `lib/auth/__tests__/messages.test.ts`, `hooks/__tests__/use-refresh.test.ts`, `components/servers/__tests__/{monitoring-badge,monitoring-card,servers-page,server-page,server-dialog,remove-server-dialog,review-host-key-dialog,host-key-dialog}.test.tsx`, `backend/tests/auth/test_sessions.py` |

Commands: run frontend commands from `frontend/` and backend commands from `backend/`. A single vitest file runs with `npx vitest run <path>`. A backend file runs with `megoocolab-runner services run test -- uv run pytest <path>`.

## Code referenced by the steps

### A. `lib/servers.ts` additions (step 1)

```ts
export const DEFAULT_INTERVAL = 5;
export type MonitoringState = "reachable" | "unreachable" | "not_monitored";
export type MonitoringReason =
  | "unreachable" | "key_refused" | "ssh_error" | "no_samples"
  | "not_an_ssh_server" | "host_key_not_pinned" | "host_key_changed";
/** What the collector last wrote about a server. `reason` is a string: a newer backend may send one we do not know. */
export type Monitoring = { state: MonitoringState; reason: string | null; since: string; last_sample_at: string | null };
// Server gets:   metrics_interval_seconds: number;  monitoring: Monitoring | null;
// ServerDraft gets: interval: number;               (after port)
// ServerBody gets:  metrics_interval_seconds: number; (after port)
// draftOf(null): interval: DEFAULT_INTERVAL;  draftOf(server): interval: server.metrics_interval_seconds
// bodyOf: metrics_interval_seconds: draft.interval
// changesOf: if (body.metrics_interval_seconds !== server.metrics_interval_seconds)
//              changes.metrics_interval_seconds = body.metrics_interval_seconds;
```

### B. `hooks/use-refresh.ts` (step 5)

```ts
"use client";

import { useEffect, useRef } from "react";

export const REFRESH_EVERY_MS = 15_000;

/**
 * Calls `refresh` every 15 seconds while the tab is visible and `active` is true, and once when the tab becomes
 * visible again. A hidden tab sends nothing.
 */
export function useRefresh(refresh: () => void, active: boolean): void {
  const latest = useRef(refresh);
  useEffect(() => {
    latest.current = refresh;
  }, [refresh]);

  useEffect(() => {
    if (!active) return;
    let timer: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      timer = setInterval(() => latest.current(), REFRESH_EVERY_MS);
    };
    const stop = () => {
      clearInterval(timer);
      timer = undefined;
    };
    function changed() {
      stop();
      if (document.visibilityState === "visible") {
        latest.current();
        start();
      }
    }
    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", changed);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", changed);
    };
  }, [active]);
}
```

### C. `lib/auth/messages.ts` additions (step 4)

```ts
export type MonitoringText = { title: string; advice: string | null };

export const MONITORING_REASONS: Record<MonitoringReason, MonitoringText> = {
  unreachable: { title: "The server did not answer.", advice: "Check the address and the port, and that the server accepts SSH connections from MegooITAdmin." },
  key_refused: { title: "The server refused the platform's key.", advice: "Run the setup script on the server with the platform's key (see Platform access)." },
  ssh_error: { title: "The SSH connection failed.", advice: "The server may offer only old algorithms, or the metrics loop could not start there." },
  no_samples: { title: "No sample for 30 seconds.", advice: "The server stopped sending samples. It may be overloaded or frozen." },
  not_an_ssh_server: { title: "Only Linux servers are monitored.", advice: null },
  host_key_not_pinned: { title: "The host key is not pinned yet.", advice: "Monitoring starts once the host key is pinned." },
  host_key_changed: { title: "The host key has changed.", advice: "Monitoring resumes once the new key is reviewed." },
};

/** The text for a server the collector has not looked at yet (`monitoring` is null). */
export const NOT_CHECKED: MonitoringText = { title: "The collector has not looked at this server yet.", advice: null };

/** The title and advice for a monitoring reason, or null for none or one this frontend does not know. */
export function monitoringText(reason: string | null): MonitoringText | null {
  return reason !== null && Object.hasOwn(MONITORING_REASONS, reason) ? MONITORING_REASONS[reason as MonitoringReason] : null;
}
```

### D. Backend (step 3)

`sessions.py`:
```python
# A request with this header set to 1 (the pages' automatic re-reads) does not move last_seen_at: it can only let a
# session end sooner, never keep it alive.
BACKGROUND_HEADER = "x-megoo-background"

async def lookup_session(db: AsyncSession, token: str | None, *, touch: bool = True) -> Lookup:
    ...  # unchanged up to the expiry check
    if touch and now - session.last_seen_at >= TOUCH_EVERY:
        session.last_seen_at = now
    return Lookup(session, None)
```
`deps.py`:
```python
async def current_session(request: Request, db: DbSession) -> AuthSession:
    background = request.headers.get(BACKGROUND_HEADER) == "1"
    lookup = await lookup_session(db, request.cookies.get(COOKIE), touch=not background)
```
Also update the module docstring of `sessions.py`: "An active one ends after session_idle_minutes without a request (background requests do not count) …".

### E. Read ordering on both pages (steps 7 and 8)

Each page keeps `const reads = useRef(0)`. A **foreground** read (the first load, after a save, a remove, a stale answer, a filter change) does `const read = ++reads.current` and applies its answer only if `read === reads.current`. A **background** read does `const read = reads.current` without bumping it, and applies its answer only if `reads.current === read` still. So a background answer never overwrites a read that started after it, and a background read never cancels a foreground one. The foreground call stays `apiFetch(path)` with **no second argument**, because the existing tests match `toHaveBeenCalledWith("/servers/s-1")` and `listCalls()` filters on `!init`. The background call is `apiFetch(path, { background: true })`.

### F. Driving `useRefresh` in the page tests (steps 7 and 8)

The page tests mock the hook and call the captured callback instead of using fake timers:
```ts
vi.mock("@/hooks/use-refresh", () => ({ useRefresh: vi.fn() }));
import { useRefresh } from "@/hooks/use-refresh";
function refreshArgs() { return vi.mocked(useRefresh).mock.lastCall!; } // [refresh, active]
async function refreshNow() { await act(async () => { refreshArgs()[0](); }); }
```
Reset it in `beforeEach` with `vi.mocked(useRefresh).mockReset()`.

## Steps

### 1. Server types carry the sample interval and the monitoring state

See step detail.

### 2. apiFetch can send a background request

See step detail.

### 3. Background requests do not count as session activity (backend)

See step detail.

### 4. Monitoring reason texts and the monitoring badge

See step detail.

### 5. The useRefresh hook

See step detail.

### 6. The Monitoring card

See step detail.

### 7. Servers list: Status column and background re-read

See step detail.

### 8. Server page: badge, Monitoring card and background re-read

See step detail.

### 9. Register and Edit dialog: the Sample interval field

See step detail.

### 10. README and the full gates

See step detail.

(The detail of each step is in the `steps` array, and the subtasks are built from it. The code it refers to is in sections A–F above.)

## Final verification

From `frontend/`: `npx tsc --noEmit`, `npx eslint src`, `npm test`, `megoocolab-runner services run web -- npm run test:image`.
From `backend/`: `megoocolab-runner services run test -- uv run pytest`, `megoocolab-runner services run image -- uv run pytest -m docker`.
From the repository root: `make test-security`.
