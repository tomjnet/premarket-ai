import {Link} from 'react-router';

import type {BriefItem} from '@/api/schemas/brief';
import {Badge} from '@/components/ui/badge';
import {SentimentBadge} from '@/features/news/components/sentiment-badge';
import {formatEtTime} from '@/lib/time';
import {safeHttpUrl} from '@/lib/url';

interface BriefItemViewProps {
  item: BriefItem;
  /** The element id citations move focus to (one per item and section). */
  anchorId?: string;
}

/**
 * One numbered item of the brief. Vendor text (headline, summary) is
 * rendered as text only; the filing link opens only an http(s) URL.
 */
export function BriefItemView({item, anchorId}: BriefItemViewProps) {
  const filing =
    item.filingUrl === null ? undefined : safeHttpUrl(item.filingUrl);
  const unconfirmed = item.verdict === 'UNVERIFIED';
  return (
    <li
      id={anchorId}
      tabIndex={anchorId === undefined ? undefined : -1}
      className="flex flex-col gap-1 rounded-md border p-3 focus:outline-2 focus:outline-ring"
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-sm font-semibold text-muted-foreground">
          <span className="sr-only">Item </span>[{item.n}]
        </span>
        <Link
          to={`/news/${item.newsId}`}
          className="font-medium break-words underline-offset-4 hover:underline"
        >
          {item.headline}
        </Link>
      </div>
      {item.summary !== null && (
        <p className="text-sm break-words">
          <span className="text-muted-foreground">AI summary: </span>
          {item.summary}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {unconfirmed ? (
          <Badge variant="warning">UNCONFIRMED</Badge>
        ) : (
          <Badge variant="success">VERIFIED</Badge>
        )}
        {item.isNew && (
          <Badge variant="outline">
            <span aria-hidden="true">NEW</span>
            <span className="sr-only">
              New: reviewed by an analyst since the morning edition
            </span>
          </Badge>
        )}
        {item.sentiment !== null && (
          <SentimentBadge sentiment={item.sentiment} />
        )}
        {item.impact !== null && (
          <span className="text-muted-foreground">
            Market impact: {item.impact}
          </span>
        )}
      </div>
      <p className="text-xs text-muted-foreground break-words">
        {item.tickers.length > 0 && `${item.tickers.join(', ')} · `}
        {item.sourceDomain} ·{' '}
        <time dateTime={item.publishedAt}>
          {formatEtTime(item.publishedAt)} ET
        </time>
        {filing !== undefined && (
          <>
            {' · '}
            <a
              href={filing.href}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="underline underline-offset-2"
            >
              Primary source: {item.filingTitle ?? 'SEC filing'} (
              {filing.hostname})
            </a>
          </>
        )}
      </p>
    </li>
  );
}
