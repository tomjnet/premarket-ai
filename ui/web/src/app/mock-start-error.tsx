/**
 * Shown instead of the app when mock mode is on but the MSW service worker
 * can't start (for example in a browser or embedded view that blocks service
 * workers). Without it the page would stay blank.
 */
export function MockStartError() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-3 p-6">
      <h1 className="text-2xl font-semibold">The mock backend didn't start</h1>
      <p role="alert">
        This page runs in mock mode, which needs a service worker, and the
        browser refused to register it.
      </p>
      <p>
        Open the dev server URL in Chrome, Edge or Firefox with service workers
        allowed, or run the dev server with VITE_API_MODE=live against a real
        backend.
      </p>
    </main>
  );
}
