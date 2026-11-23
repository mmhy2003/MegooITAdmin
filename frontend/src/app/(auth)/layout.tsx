import { ThemeSwitch } from "@/components/shell/theme-switch";
import { Wordmark } from "@/components/shell/wordmark";

/** The sign-in and set-up pages: no shell, one centred column. */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex items-center justify-between p-4">
        <Wordmark />
        <ThemeSwitch />
      </header>
      <main id="main" tabIndex={-1} className="flex flex-1 items-start justify-center px-4 py-10 outline-none sm:items-center">
        <div className="w-full max-w-md">{children}</div>
      </main>
    </div>
  );
}
