/**
 * The SIMULATION ribbon and the compliance banner. Always rendered, on every
 * page; no prop or setting can hide them.
 */
export function ComplianceNotices() {
  return (
    <section aria-label="Notices">
      <p className="bg-amber-300 px-4 py-1 text-center text-sm font-semibold text-black">
        SIMULATION: synthetic vendor data
      </p>
      <p className="border-b bg-muted px-4 py-1 text-center text-sm text-foreground">
        Decision support only, not investment advice.
      </p>
    </section>
  );
}
