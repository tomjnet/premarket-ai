import {Link} from 'react-router';

import type {NewsItem} from '@/api/schemas/news';
import {formatEtTime} from '@/lib/time';
import {cn} from '@/lib/utils';

interface NewsRowProps {
  item: NewsItem;
  /** The ticker the feed is filtered by, if any. */
  activeTicker?: string;
  onTickerClick(ticker: string): void;
  /** The feed's URL query, so the detail page can link back to it. */
  feedSearch: string;
}

/**
 * One feed item. All vendor text is rendered as plain text (React escapes
 * it): headlines can contain HTML-looking or hostile content on purpose.
 */
export function NewsRow({
  item,
  activeTicker,
  onTickerClick,
  feedSearch,
}: NewsRowProps) {
  return (
    <li
      data-feed-row
      className={cn(
        'flex flex-col gap-1 rounded-lg border p-3 md:grid md:grid-cols-[5rem_1fr] md:gap-4',
        item.isDup && 'border-dashed bg-muted/40',
      )}
    >
      <time
        dateTime={item.publishedAt}
        className="text-sm tabular-nums text-muted-foreground"
      >
        {formatEtTime(item.publishedAt)} ET
      </time>
      <div className="flex min-w-0 flex-col gap-1.5">
        <h2
          className={cn(
            'font-medium break-words',
            item.isDup && 'text-muted-foreground',
          )}
        >
          <Link
            data-row-link
            to={`/news/${item.id}`}
            state={{feedSearch}}
            className="underline-offset-4 hover:underline focus-visible:underline"
          >
            {item.headline}
          </Link>
        </h2>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {item.tickers.map(ticker => (
            <button
              key={ticker}
              type="button"
              aria-label={`Filter by ${ticker}`}
              aria-pressed={ticker === activeTicker}
              onClick={() => onTickerClick(ticker)}
              className="rounded-md border px-1.5 py-0.5 font-mono text-xs hover:bg-muted aria-pressed:bg-primary aria-pressed:text-primary-foreground"
            >
              {ticker}
            </button>
          ))}
          <span className="text-muted-foreground">{item.sourceDomain}</span>
          {/* Reserved for verdict and rule badges (later increments). */}
          <span data-slot="row-badges" />
        </div>
        <p className="text-sm break-words text-muted-foreground">
          {item.excerpt}
        </p>
        {item.isDup && (
          <p className="text-xs font-medium">
            Duplicate of {item.dupOf ?? 'an earlier item'}
          </p>
        )}
      </div>
    </li>
  );
}
