import Link from "next/link";

export function Wordmark() {
  return (
    <Link href="/" aria-label="MegooITAdmin" className="flex items-center gap-2 px-1 py-1.5">
      <span
        aria-hidden
        className="grid size-8 shrink-0 place-items-center rounded bg-cyan-ink font-brand text-sm font-bold text-on-accent shadow-(--glow-cyan)"
      >
        M
      </span>
      <span
        aria-hidden
        className="font-brand text-sm font-bold uppercase tracking-widest group-data-[collapsible=icon]:hidden"
      >
        MegooITAdmin
      </span>
    </Link>
  );
}
