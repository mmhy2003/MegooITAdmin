/** A full page load of `path`, so the proxy checks the session again. Tests mock this module. */
export function goTo(path: string): void {
  window.location.assign(path);
}
