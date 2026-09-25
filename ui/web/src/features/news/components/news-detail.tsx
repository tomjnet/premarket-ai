import {ExternalLink} from 'lucide-react';
import {Link} from 'react-router';

import type {NewsDetail} from '@/api/schemas/news';
import {
  formatEtTime,
  formatLongDate,
  formatUtcDateTime,
  newYorkDateOf,
} from '@/lib/time';
import {safeHttpUrl} from '@/lib/url';

import {bodyParagraphs} from '../detail';
import {feedSearch} from '../feed';

interface NewsDetailViewProps {
  item: NewsDetail;
}

/**
 * One news item in full. Every vendor field is rendered as plain text; the
 * source becomes a link only if it is an http(s) URL.
 */
export function NewsDetailView({item}: NewsDetailViewProps) {
  return (
    <article className="flex flex-col gap-5">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold break-words">{item.headline}</h1>
        <p className="text-sm text-muted-foreground">
          {/* UTC is shown, not only on hover: hover can't be reached by
              keyboard or touch. */}
          Published{' '}
          <time dateTime={item.publishedAt}>
            {formatLongDate(newYorkDateOf(item.publishedAt))},{' '}
            {formatEtTime(item.publishedAt)} ET
          </time>{' '}
          ({formatUtcDateTime(item.publishedAt)})
        </p>
        {item.tickers.length > 0 && (
          <ul aria-label="Tickers" className="flex flex-wrap gap-2">
            {item.tickers.map(ticker => (
              <li key={ticker}>
                <Link
                  to={{
                    pathname: '/news',
                    search: feedSearch({
                      date: item.feedDate,
                      ticker,
                      dups: false,
                    }),
                  }}
                  aria-label={`${ticker}: show its news in the feed`}
                  className="rounded-md border px-1.5 py-0.5 font-mono text-xs hover:bg-muted"
                >
                  {ticker}
                </Link>
              </li>
            ))}
          </ul>
        )}
        {/* Reserved for verdict and rule badges (later increments). */}
        <div data-slot="detail-badges" />
      </header>

      <SourceLine url={item.sourceUrl} domain={item.sourceDomain} />

      <div className="flex max-w-prose flex-col gap-3 leading-relaxed">
        {bodyParagraphs(item.body).map((paragraph, index) => (
          <p key={index} className="whitespace-pre-line break-words">
            {paragraph}
          </p>
        ))}
      </div>

      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 border-t pt-4 text-sm">
        <dt className="text-muted-foreground">Feed date</dt>
        <dd>{formatLongDate(item.feedDate)}</dd>
        <dt className="text-muted-foreground">Vendor item id</dt>
        <dd className="font-mono break-all">{item.vendorItemId}</dd>
        <dt className="text-muted-foreground">Duplicate</dt>
        <dd className="break-all">
          {item.isDup
            ? `Yes, duplicate of ${item.dupOf ?? 'an earlier item'}`
            : 'No'}
        </dd>
        <dt className="text-muted-foreground">Synthetic</dt>
        <dd>{item.synthetic ? 'Yes (simulated vendor data)' : 'No'}</dd>
      </dl>
    </article>
  );
}

interface SourceLineProps {
  url: string;
  domain: string;
}

/**
 * The vendor's source. The link text is the host the link really opens, not
 * the vendor's `source_domain`, so a mismatch can't disguise where it goes.
 */
function SourceLine({url, domain}: SourceLineProps) {
  const link = safeHttpUrl(url);
  if (link === undefined) {
    return (
      <p className="text-sm">
        Source: {domain}{' '}
        <span className="text-muted-foreground">
          (link not shown: not a web address)
        </span>
      </p>
    );
  }
  return (
    <p className="text-sm">
      Source: {domain}
      {link.hostname !== domain && (
        <span className="text-muted-foreground">
          {' '}
          (the link opens a different site)
        </span>
      )}{' '}
      ·{' '}
      <a
        href={link.href}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="inline-flex items-center gap-1 font-medium underline underline-offset-4"
      >
        {link.hostname}
        <ExternalLink aria-hidden="true" className="size-3.5" />
        <span className="sr-only">(opens in a new tab)</span>
      </a>
    </p>
  );
}
