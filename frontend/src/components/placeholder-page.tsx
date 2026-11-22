import { Badge } from "@/components/ui/badge";
import { navItem } from "@/lib/navigation";

/** The body of a page that is not built yet; the page's h1 is in the header. */
export function PlaceholderPage({ href }: { href: string }) {
  const item = navItem(href);
  return (
    <section className="max-w-xl space-y-3 rounded-lg border bg-card p-6 shadow-sm">
      <item.icon aria-hidden className="size-8 text-cyan-ink" />
      <h2 className="text-xl font-semibold">{item.title}</h2>
      <p className="text-muted-foreground">{item.description}</p>
      <Badge variant="outline">Not built yet</Badge>
    </section>
  );
}
