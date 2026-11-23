import { NextResponse, type NextRequest } from "next/server";
import { fetchSession, SESSION_COOKIE } from "@/lib/auth/backend";
import { gateRedirect } from "@/lib/auth/gate";

/**
 * The page gate (design decision 7): every page request asks the backend about its session and is redirected by
 * the gate table. The check is not in the `(app)` layout because Next.js renders a page segment without its layout
 * on client navigation, so a layout check can be skipped; this runs before every request.
 */
export async function proxy(request: NextRequest) {
  const session = await fetchSession(request.cookies.get(SESSION_COOKIE)?.value);
  const target = gateRedirect(session?.status ?? null, request.nextUrl.pathname, request.nextUrl.search);
  return target ? NextResponse.redirect(new URL(target, request.url)) : NextResponse.next();
}

export const config = { matcher: ["/((?!_next/static|_next/image|icon.svg).*)"] };
