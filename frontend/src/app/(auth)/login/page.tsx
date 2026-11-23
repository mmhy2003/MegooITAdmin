import type { Metadata } from "next";
import { initialStep, LoginFlow } from "@/components/auth/login-flow";
import { safeNext } from "@/lib/auth/gate";
import { getSession } from "@/lib/auth/server";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string | string[] }> }) {
  const [{ next }, session] = await Promise.all([searchParams, getSession()]);
  return (
    <LoginFlow initialStep={initialStep(session?.status)} next={typeof next === "string" ? safeNext(next) : null} />
  );
}
