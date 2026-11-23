import Link from "next/link";
import { SettingsTabs } from "@/components/settings/settings-tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { requireUser } from "@/lib/auth/server";

/** Settings is the Owner's: anyone else gets a notice instead of its pages. */
export default async function SettingsLayout({ children }: { children: React.ReactNode }) {
  const user = await requireUser();
  if (user.platform_role !== "owner") {
    return (
      <Card className="max-w-xl">
        <CardHeader>
          <CardTitle>
            <h2>Settings are for the Owner</h2>
          </CardTitle>
          <CardDescription>
            Only the Owner of this installation manages people and server groups. Your own access is on Profile and
            security.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/profile" className="text-sm underline underline-offset-4">
            Profile and security
          </Link>
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="space-y-6">
      <SettingsTabs />
      {children}
    </div>
  );
}
