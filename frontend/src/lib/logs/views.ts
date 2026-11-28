import { apiFetch } from "@/lib/api";
import { LEVEL_GROUPS } from "@/lib/logs/levels";
import {
  type LogSource,
  normalizeSource,
  queryOf,
  type ViewSettings,
  type ViewState,
  wire,
} from "@/lib/logs/sources";

export type LogView = {
  id: string;
  name: string;
  shared: boolean;
  owner_name: string;
  is_mine: boolean;
  can_edit: boolean;
  sources: LogSource[];
  settings: ViewSettings;
  updated_at: string;
};
export type ViewBody = { name: string; shared: boolean; sources: Record<string, unknown>[]; settings: ViewSettings };

export const MAX_VIEW_NAME = 80;

/** The views the person may open, each with only the sources that keep the rules of the address. */
export async function listViews(): Promise<LogView[]> {
  const views = await apiFetch<(Omit<LogView, "sources"> & { sources: Record<string, unknown>[] })[]>("/log-views");
  return views.map((view) => ({
    ...view,
    sources: view.sources.map(normalizeSource).filter((s): s is LogSource => s !== null),
  }));
}

export function createView(body: ViewBody): Promise<LogView> {
  return apiFetch<LogView>("/log-views", { method: "POST", body });
}

export function updateView(id: string, body: ViewBody): Promise<LogView> {
  return apiFetch<LogView>(`/log-views/${id}`, { method: "PUT", body });
}

export function deleteView(id: string): Promise<void> {
  return apiFetch<void>(`/log-views/${id}`, { method: "DELETE" });
}

/** What saving a view sends: a container keeps its name, to be found again once it is recreated. */
export function bodyOf(state: ViewState, name: string, shared: boolean): ViewBody {
  const { settings } = state;
  return {
    name,
    shared,
    sources: state.sources.map((s) => (s.kind === "container" ? { ...wire(s), name: s.name } : wire(s))),
    settings: { ...settings, levels: LEVEL_GROUPS.filter((level) => settings.levels.includes(level)) },
  };
}

export function stateOf(view: LogView): ViewState {
  return { sources: view.sources, settings: view.settings };
}

/** Whether the viewer shows something else than the saved view: other sources, another order or other settings. */
export function differs(state: ViewState, view: LogView): boolean {
  return queryOf(state) !== queryOf(stateOf(view));
}
