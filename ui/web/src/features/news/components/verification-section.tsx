import {ExternalLink} from 'lucide-react';

import type {Verification, VerifyEvidence} from '@/api/schemas/news';
import {formatEtTime, formatLongDate, newYorkDateOf} from '@/lib/time';
import {safeHttpUrl} from '@/lib/url';

import {evidenceBadge, reasonCodeText} from '../rules';
import {
  VERDICT_MEANING,
  confidenceText,
  impactText,
  reviewBadge,
  reviewReasonText,
  verdictBadge,
  verdictText,
} from '../verdicts';

import {RuleBadgeView} from './rule-badges';

interface VerificationSectionProps {
  verification: Verification;
  /** The item is a duplicate: this is its original's verification. */
  inherited: boolean;
}

/**
 * How the AI reached the verdict: the verdict and its confidence, the
 * rule-based and the judge's verdicts, the review, and the numbered
 * evidence (E1, E2... as the judge saw it). Everything is server or model
 * text: plain text only; links only through `safeHttpUrl`.
 */
export function VerificationSection({
  verification,
  inherited,
}: VerificationSectionProps) {
  const verdict = verification.verdict;
  const badge =
    verdict === null
      ? undefined
      : verdictBadge({
          verdict,
          verdictSource: inherited ? 'inherited' : 'ai',
        });
  const review = reviewBadge(verification.reviewStatus);
  return (
    <section
      aria-labelledby="verification-heading"
      className="flex flex-col gap-3 border-t pt-4"
    >
      <h2 id="verification-heading" className="text-lg font-semibold">
        Verification
      </h2>
      {inherited && (
        <p className="text-sm text-muted-foreground">
          This item is a duplicate: it shows the verification of the original
          story.
        </p>
      )}
      {verification.status === 'FAILED' || verdict === null ? (
        <p className="text-sm">
          The verification of this item failed. Treat it as unverified.
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="flex flex-wrap items-center gap-2">
            {badge !== undefined && <RuleBadgeView badge={badge} />}
            {review !== undefined && <RuleBadgeView badge={review} />}
            {verification.confidence !== null && (
              <span className="text-sm">
                Confidence {confidenceText(verification.confidence)}
              </span>
            )}
          </p>
          <p className="text-sm text-muted-foreground">
            {verdictText(verdict)}: {VERDICT_MEANING[verdict]} Checked by rules
            and a language model; it can be wrong.
          </p>
          {verification.rationale !== '' && (
            <p className="break-words">{verification.rationale}</p>
          )}
        </div>
      )}
      <HowItWasDecided verification={verification} />
      <ReviewLine verification={verification} />
      {verification.evidence.length > 0 && (
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-semibold">Evidence</h3>
          <ol className="flex flex-col gap-2 text-sm">
            {verification.evidence.map(entry => (
              <EvidenceRow key={entry.seq} entry={entry} />
            ))}
          </ol>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Prompt {verification.promptVersion} ·{' '}
        <time dateTime={verification.verifiedAt}>
          {formatLongDate(newYorkDateOf(verification.verifiedAt))},{' '}
          {formatEtTime(verification.verifiedAt)} ET
        </time>
      </p>
    </section>
  );
}

function HowItWasDecided({verification}: {verification: Verification}) {
  const rows: Array<[string, string]> = [];
  if (verification.ruleVerdict !== null) {
    const confidence =
      verification.ruleConfidence === null
        ? ''
        : ` (${confidenceText(verification.ruleConfidence)})`;
    rows.push([
      'Rule checks',
      `${verdictText(verification.ruleVerdict)}${confidence}`,
    ]);
  }
  if (verification.judgeVerdict !== null) {
    const confidence =
      verification.judgeConfidence === null
        ? ''
        : ` (${confidenceText(verification.judgeConfidence)})`;
    const model =
      verification.judgeModel === null ? '' : `, ${verification.judgeModel}`;
    rows.push([
      verification.escalated
        ? 'LLM judge (cloud, uncertain item)'
        : 'LLM judge',
      `${verdictText(verification.judgeVerdict)}${confidence}${model}`,
    ]);
  } else if (verification.ruleVerdict === 'FAKE') {
    rows.push(['LLM judge', 'Not asked: a hard rule decides FAKE']);
  }
  if (verification.reasonCodes.length > 0) {
    rows.push([
      'Reason codes',
      verification.reasonCodes.map(reasonCodeText).join(', '),
    ]);
  }
  if (verification.impact !== null) {
    rows.push(['Market impact', impactText(verification.impact)]);
  }
  if (rows.length === 0) {
    return null;
  }
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.map(([term, value]) => (
        <div key={term} className="contents">
          <dt className="text-muted-foreground">{term}</dt>
          <dd className="break-words">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ReviewLine({verification}: {verification: Verification}) {
  const review = verification.review;
  if (review === null) {
    return null;
  }
  if (review.status === 'PENDING') {
    return (
      <p className="text-sm">
        Waiting for an analyst:{' '}
        {review.reasons.map(reviewReasonText).join(', ').toLowerCase()}.
      </p>
    );
  }
  if (review.status === 'EXPIRED') {
    return (
      <p className="text-sm">
        Nobody reviewed it before the market opened; the AI verdict stands.
      </p>
    );
  }
  const who = review.reviewer ?? 'An analyst';
  const verdict =
    review.finalVerdict === null ? '' : verdictText(review.finalVerdict);
  return (
    <p className="text-sm break-words">
      {review.status === 'OVERRIDDEN'
        ? `${who} changed the verdict from ${verdictText(review.aiVerdict)} to ${verdict}`
        : `${who} approved the verdict ${verdict}`}
      {review.comment === null ? '.' : `: ${review.comment}`}
    </p>
  );
}

function EvidenceRow({entry}: {entry: VerifyEvidence}) {
  const link = entry.url === null ? undefined : safeHttpUrl(entry.url);
  return (
    <li className="flex flex-col items-start gap-1 sm:flex-row sm:gap-2">
      <span className="font-mono text-xs text-muted-foreground">
        E{entry.seq}
      </span>
      <RuleBadgeView badge={evidenceBadge(entry)} />
      <span className="break-words">
        {entry.message}
        {link !== undefined && (
          <>
            {' '}
            <a
              href={link.href}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="inline-flex items-center gap-1 font-medium underline underline-offset-4"
            >
              {entry.title ?? link.hostname}
              <ExternalLink aria-hidden="true" className="size-3.5" />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          </>
        )}
      </span>
    </li>
  );
}
