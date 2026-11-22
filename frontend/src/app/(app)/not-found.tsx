import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <section className="max-w-xl space-y-4">
      <h2 className="text-xl font-semibold">Page not found</h2>
      <p className="text-muted-foreground">There is no page at this address.</p>
      <Button asChild>
        <Link href="/">Back to the dashboard</Link>
      </Button>
    </section>
  );
}
