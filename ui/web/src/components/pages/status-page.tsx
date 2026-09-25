import type {ReactNode} from 'react';
import {Link} from 'react-router';

interface StatusPageProps {
  title: string;
  children: ReactNode;
}

/** A short message page (403, 404, errors) with a way back to the feed. */
export function StatusPage({title, children}: StatusPageProps) {
  return (
    <section className="mx-auto flex max-w-xl flex-col gap-3 py-12">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <div className="text-muted-foreground">{children}</div>
      <p>
        <Link to="/" className="font-medium underline underline-offset-4">
          Back to the news feed
        </Link>
      </p>
    </section>
  );
}

/** 404: shown for any route the app doesn't know. */
export function NotFoundPage() {
  return (
    <StatusPage title="Page not found">
      There is no page at this address.
    </StatusPage>
  );
}

/** 403: shown by a route guard when the user's role can't see the page. */
export function ForbiddenPage() {
  return (
    <StatusPage title="You don't have access to this page">
      Your role can't open this page. Ask an administrator if you need it.
    </StatusPage>
  );
}
