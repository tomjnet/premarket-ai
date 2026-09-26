import {ExternalLink} from 'lucide-react';
import {Link} from 'react-router';

import type {ChatSource} from '@/api/schemas/chat';
import {Badge} from '@/components/ui/badge';
import {formatLongDate} from '@/lib/time';
import {safeHttpUrl} from '@/lib/url';

import {sourceKindLabel, vendorNewsId} from '../chat';

interface SourceListProps {
  sources: readonly ChatSource[];
  /** The numbers the final answer cites, once it is done. */
  cited?: readonly number[];
  /** The element id of source `n`, the target of its citation buttons. */
  sourceId(n: number): string;
}

/**
 * The numbered sources of an answer. Trusted sources open their official
 * page in a new tab; vendor items are labelled unverified and open the
 * item in the app. Titles and snippets are rendered as text.
 */
export function SourceList({sources, cited, sourceId}: SourceListProps) {
  if (sources.length === 0) {
    return <p className="text-sm text-muted-foreground">No sources found.</p>;
  }
  return (
    <ol aria-label="Sources" className="flex flex-col gap-3">
      {sources.map(source => (
        <li
          key={source.n}
          id={sourceId(source.n)}
          tabIndex={-1}
          className="flex flex-col gap-1 rounded-lg border p-3 text-sm focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono font-semibold">[{source.n}]</span>
            <Badge variant={source.trusted ? 'secondary' : 'warning'}>
              {source.trusted
                ? sourceKindLabel(source.kind)
                : 'Vendor item (unverified)'}
            </Badge>
            {source.ticker !== null && (
              <span className="font-mono text-xs">{source.ticker}</span>
            )}
            {source.publishedAt !== null && (
              <time
                dateTime={source.publishedAt}
                className="text-xs text-muted-foreground"
              >
                {formatLongDate(source.publishedAt)}
              </time>
            )}
            {cited?.includes(source.n) === true && (
              <span className="text-xs font-medium">Cited</span>
            )}
          </div>
          <SourceTitle source={source} />
          <p className="break-words text-muted-foreground">{source.snippet}</p>
        </li>
      ))}
    </ol>
  );
}

interface SourceTitleProps {
  source: ChatSource;
}

function SourceTitle({source}: SourceTitleProps) {
  const title = source.title === '' ? 'Untitled source' : source.title;
  if (!source.trusted) {
    const id = vendorNewsId(source.url);
    if (id === undefined) {
      return <p className="font-medium break-words">{title}</p>;
    }
    return (
      <p className="font-medium break-words">
        <Link to={`/news/${id}`} className="underline underline-offset-4">
          {title}
        </Link>
      </p>
    );
  }
  const link = safeHttpUrl(source.url);
  if (link === undefined) {
    return <p className="font-medium break-words">{title}</p>;
  }
  return (
    <p className="font-medium break-words">
      <a
        href={link.href}
        target="_blank"
        rel="noopener noreferrer nofollow"
        className="underline underline-offset-4"
      >
        {title}
        <ExternalLink
          aria-hidden="true"
          className="ml-1 inline size-3.5 align-baseline"
        />
        <span className="sr-only"> (opens {link.hostname} in a new tab)</span>
      </a>
    </p>
  );
}
