export type CheckKind = "containers" | "processes" | "services" | "logins" | "updates" | "certificates";
export type CheckState = "ok" | "not_available" | "denied" | "timeout" | "failed" | "not_checked";
export type ContainersData = { total: number; running: number; not_running: number };
export type Proc = { pid: number; name: string; user: string; cpu_percent: number; memory_bytes: number };
export type ProcessesData = { by_cpu: Proc[]; by_memory: Proc[] };
export type ServicesData = {
  total: number;
  running: number;
  failed: number;
  failed_units: { unit: string; description: string }[];
};
export type LoginsData = { failed_24h: number; top_sources: { address: string; count: number }[] };
/** `security` and `reboot_required` are null when the package manager cannot tell. */
export type UpdatesData = {
  manager: "apt" | "dnf";
  pending: number;
  security: number | null;
  reboot_required: boolean | null;
  lists_refreshed_at: string | null;
};
export type Certificate = { port: number; subject: string; issuer: string; not_after: string; fingerprint_sha256: string };
export type CertificatesData = { certificates: Certificate[] };
export type CheckData = {
  containers: ContainersData;
  processes: ProcessesData;
  services: ServicesData;
  logins: LoginsData;
  updates: UpdatesData;
  certificates: CertificatesData;
};
/** The latest result of one check. `data` is the last good result, which a later failed run keeps. */
export type ServerCheck<K extends CheckKind = CheckKind> = {
  kind: K;
  status: CheckState;
  checked_at: string | null;
  every_seconds: number;
  data: CheckData[K] | null;
  data_at: string | null;
};
export type ChecksResponse = { can_view_processes: boolean; checks: ServerCheck[] };
/** `state` is a string: a newer Docker may report one we do not know. */
export type Container = {
  container_id: string;
  runtime: string;
  name: string;
  image: string;
  compose_project: string | null;
  compose_service: string | null;
  state: string;
  status: string;
  first_seen_at: string;
  last_seen_at: string;
};
export type ContainerGroup = { project: string | null; containers: Container[] };
export type Tone = "pink" | "amber" | "green" | "muted";

export const TONE_CLASSES: Record<Tone, string> = {
  pink: "border-pink text-pink-ink",
  amber: "border-amber text-amber-ink",
  green: "border-green text-green-ink",
  muted: "text-muted-foreground",
};

/** `not_available.text` is a fallback: the cards say why with `NOT_AVAILABLE`. */
export const STATE_TEXTS: Record<Exclude<CheckState, "ok">, { badge: string; text: string }> = {
  not_checked: { badge: "Not checked yet", text: "The collector has not run this check yet." },
  not_available: { badge: "Not available", text: "This check is not available on this server." },
  denied: {
    badge: "Not allowed",
    text: "sudo refused megoo-ctl on this server. Run megoo-setup.sh on it again (Platform access card).",
  },
  timeout: { badge: "Could not be checked", text: "The check took too long." },
  failed: { badge: "Could not be checked", text: "The check failed or printed something unexpected." },
};

export const NOT_AVAILABLE: Record<CheckKind, string> = {
  containers: "Docker is not installed on this server.",
  processes: "ps is not installed on this server.",
  services: "systemd is not running on this server.",
  logins: "journalctl is not available on this server.",
  updates: "Neither apt nor dnf could answer from what this server has cached.",
  certificates: "openssl is not installed on this server.",
};

/** The check of `kind`; one the response does not carry reads as not checked yet. */
export function checkOf<K extends CheckKind>(response: ChecksResponse, kind: K): ServerCheck<K> {
  const found = response.checks.find((check) => check.kind === kind);
  if (found) return found as ServerCheck<K>;
  return { kind, status: "not_checked", checked_at: null, every_seconds: 0, data: null, data_at: null };
}

const byName = (a: Container, b: Container) => a.name.localeCompare(b.name);

/** One group per Compose project, by name, with the containers of no project last. */
export function groupContainers(containers: Container[]): ContainerGroup[] {
  const groups = new Map<string | null, Container[]>();
  for (const item of containers) {
    const group = groups.get(item.compose_project) ?? [];
    group.push(item);
    groups.set(item.compose_project, group);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a === null ? 1 : b === null ? -1 : a.localeCompare(b)))
    .map(([project, items]) => ({ project, containers: items.sort(byName) }));
}

/** A result is old once more than three intervals have passed since the check last ran. */
export function isOld(check: ServerCheck, now: Date): boolean {
  if (check.checked_at === null) return false;
  return now.getTime() - new Date(check.checked_at).getTime() > 3 * check.every_seconds * 1000;
}

function count(n: number, unit: string): string {
  return `${n} ${unit}${n === 1 ? "" : "s"}`;
}

export function agoText(iso: string, now: Date): string {
  const seconds = Math.floor((now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${count(Math.floor(seconds / 60), "minute")} ago`;
  if (seconds < 86_400) return `${count(Math.floor(seconds / 3600), "hour")} ago`;
  return `${count(Math.floor(seconds / 86_400), "day")} ago`;
}

export function everyText(seconds: number): string {
  const [n, unit] =
    seconds % 3600 === 0 ? [seconds / 3600, "hour"] : seconds % 60 === 0 ? [seconds / 60, "minute"] : [seconds, "second"];
  return n === 1 ? `every ${unit}` : `every ${n} ${unit}s`;
}

export function certificateTone(notAfter: string, now: Date): { tone: Tone; label: string } {
  const left = new Date(notAfter).getTime() - now.getTime();
  if (left <= 0) return { tone: "pink", label: "Expired" };
  const days = Math.ceil(left / 86_400_000);
  if (days >= 30) return { tone: "green", label: "Valid" };
  return { tone: days < 7 ? "pink" : "amber", label: `Expires in ${count(days, "day")}` };
}

export function containerTone(state: string): Tone {
  if (state === "running") return "green";
  if (state === "restarting" || state === "paused") return "amber";
  return "muted";
}
