import {ExternalLink} from 'lucide-react';
import {Link} from 'react-router';

import type {AiDetail, NewsDetail, Sentiment} from '@/api/schemas/news';
import {
  formatEtTime,
  formatLongDate,
  formatUtcDateTime,
  newYorkDateOf,
} from '@/lib/time';
import {safeHttpUrl} from '@/lib/url';

import {aiStatusText} from '../ai';
import {bodyParagraphs} from '../detail';
import {feedSearch} from '../feed';
import {dupTypeText, evidenceBadge, ruleBadges} from '../rules';
import {verdictBadges} from '../verdicts';

import {RuleBadgeView, RuleBadges} from './rule-badges';
import {SentimentBadge} from './sentiment-badge';
import {VerificationSection} from './verification-section';

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
                      flagged: false,
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
        {/* The verdict first (increment 4), then the check badges. */}
        <div data-slot="detail-badges" className="flex flex-col gap-1.5">
          <RuleBadges badges={verdictBadges(item)} label="Verdict" />
          <RuleBadges badges={ruleBadges(item)} />
        </div>
      </header>

      <SourceLine url={item.sourceUrl} domain={item.sourceDomain} />

      <div className="flex max-w-prose flex-col gap-3 leading-relaxed">
        {bodyParagraphs(item.body).map((paragraph, index) => (
          <p key={index} className="whitespace-pre-line break-words">
            {paragraph}
          </p>
        ))}
      </div>

      <RuleChecks item={item} />

      {item.ai !== null && (
        <AiSection
          ai={item.ai}
          summary={item.summary}
          sentiment={item.sentiment}
        />
      )}

      {item.verification !== null && (
        <VerificationSection
          verification={item.verification}
          inherited={item.verdictSource === 'inherited'}
        />
      )}
      {item.verification === null && item.verdictSource === 'inherited' && (
        <section
          aria-labelledby="verification-heading"
          className="flex flex-col gap-2 border-t pt-4"
        >
          <h2 id="verification-heading" className="text-lg font-semibold">
            Verification
          </h2>
          <p className="text-sm">
            A copy of an earlier day's story re-served as new: shown as
            MISLEADING (the original was verified on its own date).
          </p>
        </section>
      )}

      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 border-t pt-4 text-sm">
        <dt className="text-muted-foreground">Feed date</dt>
        <dd>{formatLongDate(item.feedDate)}</dd>
        <dt className="text-muted-foreground">Vendor item id</dt>
        <dd className="font-mono break-all">{item.vendorItemId}</dd>
        <dt className="text-muted-foreground">Duplicate</dt>
        <dd className="break-all">
          {item.isDup
            ? `Yes, duplicate of ${item.dupOf ?? 'an earlier item'}${
                item.dupType === null ? '' : ` (${dupTypeText(item.dupType)})`
              }`
            : 'No'}
        </dd>
        {item.copies > 0 && (
          <>
            <dt className="text-muted-foreground">Copies of this story</dt>
            <dd>{item.copies}</dd>
          </>
        )}
        <dt className="text-muted-foreground">Synthetic</dt>
        <dd>{item.synthetic ? 'Yes (simulated vendor data)' : 'No'}</dd>
      </dl>
    </article>
  );
}

interface RuleChecksProps {
  item: NewsDetail;
}

/**
 * What the backend's deterministic rule checks found. Messages come from
 * the server and are rendered as plain text.
 */
function RuleChecks({item}: RuleChecksProps) {
  let summary: string | undefined;
  if (!item.rulesChecked) {
    summary = "Rule checks haven't run for this item yet.";
  } else if (item.ruleEvidence.every(evidence => evidence.code === null)) {
    summary = 'No rule flagged this item.';
  }
  return (
    <section
      aria-labelledby="rule-checks-heading"
      className="flex flex-col gap-2 border-t pt-4"
    >
      <h2 id="rule-checks-heading" className="text-lg font-semibold">
        Rule checks
      </h2>
      {summary !== undefined && (
        <p className="text-sm text-muted-foreground">{summary}</p>
      )}
      {item.rulesChecked && item.ruleEvidence.length > 0 && (
        <ul className="flex flex-col gap-2 text-sm">
          {item.ruleEvidence.map((evidence, index) => (
            <li
              key={index}
              className="flex flex-col items-start gap-1 sm:flex-row sm:gap-2"
            >
              <RuleBadgeView badge={evidenceBadge(evidence)} />
              <span className="break-words">{evidence.message}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

interface AiSectionProps {
  ai: AiDetail;
  summary: string | null;
  sentiment: Sentiment | null;
}

/**
 * What the AI run made of the item. Everything here is model or server
 * output about untrusted vendor text: plain text only, and labelled as
 * machine-written.
 */
function AiSection({ai, summary, sentiment}: AiSectionProps) {
  return (
    <section
      aria-labelledby="ai-heading"
      className="flex flex-col gap-3 border-t pt-4"
    >
      <h2 id="ai-heading" className="text-lg font-semibold">
        AI
      </h2>
      <p className="text-sm text-muted-foreground">
        {aiStatusText(ai.status)}. Written by a language model from the vendor's
        text; it can be wrong.
      </p>
      {summary !== null && (
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-semibold">Summary</h3>
          <p className="break-words">{summary}</p>
          {ai.summarySource === 'fallback' && (
            <p className="text-sm text-muted-foreground">
              Lead sentence: the model couldn't summarize this item.
            </p>
          )}
        </div>
      )}
      {sentiment !== null && (
        <p>
          <SentimentBadge sentiment={sentiment} />
        </p>
      )}
      {ai.status === 'DONE' && (
        <>
          <div className="flex flex-col gap-1">
            <h3 className="text-sm font-semibold">Companies</h3>
            {ai.companies.length === 0 ? (
              <p className="text-sm text-muted-foreground">None found.</p>
            ) : (
              <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                {ai.companies.map((company, index) => (
                  <li key={index} className="break-words">
                    {company.name}
                    {company.ticker !== null && (
                      <span className="font-mono"> ({company.ticker})</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="flex flex-col gap-1">
            <h3 className="text-sm font-semibold">Claims</h3>
            {ai.claims.length === 0 ? (
              <p className="text-sm text-muted-foreground">None found.</p>
            ) : (
              <ul className="flex list-disc flex-col gap-1 pl-5 text-sm">
                {ai.claims.map((claim, index) => (
                  <li key={index} className="break-words">
                    {claim}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
      {ai.evidence.length > 0 && (
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-semibold">AI checks</h3>
          <ul className="flex flex-col gap-2 text-sm">
            {ai.evidence.map((evidence, index) => (
              <li
                key={index}
                className="flex flex-col items-start gap-1 sm:flex-row sm:gap-2"
              >
                <RuleBadgeView badge={evidenceBadge(evidence)} />
                <span className="break-words">{evidence.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Model {ai.model} · prompt {ai.promptVersion} ·{' '}
        <time dateTime={ai.enrichedAt}>
          {formatLongDate(newYorkDateOf(ai.enrichedAt))},{' '}
          {formatEtTime(ai.enrichedAt)} ET
        </time>
      </p>
    </section>
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
