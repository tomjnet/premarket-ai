import {ArrowLeft} from 'lucide-react';
import type {ReactNode} from 'react';
import {Link, useLocation, useParams} from 'react-router';

import {HttpError} from '@/api/errors';
import {LoadError} from '@/components/load-error';
import {Skeleton} from '@/components/ui/skeleton';
import {todayInNewYork} from '@/lib/time';

import {NewsDetailView} from './components/news-detail';
import {backToFeedSearch, parseNewsId} from './detail';
import {useNewsItem} from './hooks/use-news-item';

/** `/news/:id`: one news item, with a way back to the feed as it was. */
export function NewsDetailPage() {
  const params = useParams();
  const location = useLocation();
  const id = parseNewsId(params.id);
  const item = useNewsItem(id);
  const backTo = `/news${backToFeedSearch(
    location.state,
    item.data?.feedDate,
    todayInNewYork(),
  )}`;

  const notFound =
    id === undefined ||
    (item.error instanceof HttpError && item.error.status === 404);
  // Every state has an h1, so a screen reader finds the page heading while
  // the item loads or after an error.
  let content: ReactNode;
  if (notFound) {
    content = (
      <section className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">This item doesn't exist</h1>
        <p className="text-muted-foreground">
          The link may be wrong, or the item isn't in the feed (yet).
        </p>
      </section>
    );
  } else if (item.data !== undefined) {
    content = <NewsDetailView item={item.data} />;
  } else if (item.isError) {
    content = (
      <>
        <h1 className="text-2xl font-semibold">News item</h1>
        <LoadError
          title="Couldn't load this item"
          error={item.error}
          onRetry={() => void item.refetch()}
        />
      </>
    );
  } else {
    content = (
      <>
        <h1 className="sr-only">News item</h1>
        <DetailSkeleton />
      </>
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <p>
        <Link
          to={backTo}
          className="inline-flex items-center gap-1 text-sm font-medium underline underline-offset-4"
        >
          <ArrowLeft aria-hidden="true" className="size-4" />
          Back to the feed
        </Link>
      </p>
      {content}
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div aria-busy="true" className="flex flex-col gap-3">
      <p role="status" className="sr-only">
        Loading the item…
      </p>
      <Skeleton className="h-8 w-4/5" />
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-2/3" />
    </div>
  );
}
