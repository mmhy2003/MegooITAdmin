import { describe, expect, it } from "vitest";
import { NAV_ITEMS } from "../src/lib/navigation";

const BASE = process.env.FRONTEND_URL;
// The stub backend (tools/test-services/stub-backend.Caddyfile) answers "active" for this cookie only.
const SIGNED_IN = "megoo_session=image-test-session";
if (!BASE) {
  throw new Error("FRONTEND_URL is not set. Run the image check from frontend/ with: megoocolab-runner services run web -- npm run test:image");
}

async function get(path: string, init?: RequestInit) {
  const response = await fetch(new URL(path, BASE), init);
  return { status: response.status, html: await response.text() };
}
function sidebarTag(html: string): string {
  const tag = /<div[^>]*data-slot="sidebar"[^>]*>/.exec(html);
  if (!tag) throw new Error("no sidebar in the page");
  return tag[0];
}

describe("the frontend image", () => {
  it("sends a request without a session to the sign-in page", async () => {
    const home = await fetch(new URL("/", BASE), { redirect: "manual" });
    expect(home.status).toBe(307);
    expect(home.headers.get("location")).toMatch(/\/login$/);
    const servers = await fetch(new URL("/servers", BASE), { redirect: "manual" });
    expect(servers.status).toBe(307);
    expect(servers.headers.get("location")).toMatch(/\/login\?next=%2Fservers$/);
  });

  it("serves the sign-in page with the theme script in the head", async () => {
    const { status, html } = await get("/login", { redirect: "manual" });
    expect(status).toBe(200);
    expect(html).toContain("Sign in");
    expect(html.slice(html.indexOf("<head"), html.indexOf("<body"))).toContain("megoo-theme");
  });

  it("serves the dashboard with the wordmark and a link to every page", async () => {
    const { status, html } = await get("/", { headers: { cookie: SIGNED_IN } });
    expect(status).toBe(200);
    expect(html).toContain("MegooITAdmin");
    for (const item of NAV_ITEMS) expect(html).toContain(`href="${item.href}"`);
  });

  it("runs the theme script in the head, before the body", async () => {
    const { html } = await get("/", { headers: { cookie: SIGNED_IN } });
    const head = html.slice(html.indexOf("<head"), html.indexOf("<body"));
    expect(head).toContain("megoo-theme");
    expect(head).toContain("dataset.theme");
  });

  it("renders the sidebar open without a sidebar_state cookie and collapsed when sidebar_state is false", async () => {
    expect(sidebarTag((await get("/", { headers: { cookie: SIGNED_IN } })).html)).toContain('data-state="expanded"');
    expect(sidebarTag((await get("/", { headers: { cookie: SIGNED_IN + "; sidebar_state=false" } })).html)).toContain('data-state="collapsed"');
  });

  it("serves the servers page with its title", async () => {
    const { status, html } = await get("/servers", { headers: { cookie: SIGNED_IN } });
    expect(status).toBe(200);
    expect(html).toContain("<title>Servers · MegooITAdmin</title>");
  });

  it("answers 404 for an unknown address and keeps the navigation", async () => {
    const { status, html } = await get("/no-such-page", { headers: { cookie: SIGNED_IN } });
    expect(status).toBe(404);
    expect(html).toContain('aria-label="Main"');
    expect(html).toContain("Page not found");
  });
});
