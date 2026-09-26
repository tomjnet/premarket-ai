import {useId, useState} from 'react';
import type {FormEvent} from 'react';
import {Link} from 'react-router';

import type {Verdict} from '@/api/schemas/news';
import type {ReviewDecision, ReviewTask} from '@/api/schemas/verify';
import {Button} from '@/components/ui/button';
import {Label} from '@/components/ui/label';
import {Textarea} from '@/components/ui/textarea';
import {RuleBadgeView} from '@/features/news/components/rule-badges';
import {reasonCodeText} from '@/features/news/rules';
import {
  VERDICTS,
  confidenceText,
  impactText,
  reviewReasonText,
  verdictBadge,
  verdictText,
} from '@/features/news/verdicts';

import {decisionErrorMessage, overrideProblem} from '../review';

interface ReviewTaskCardProps {
  task: ReviewTask;
  /** Sends the decision; rejects with the API error. */
  onDecide(decision: ReviewDecision): Promise<unknown>;
}

/**
 * One item waiting for an analyst: what the AI decided and why, then
 * "Approve" or "Change verdict" (a new verdict and a required comment).
 * The headline and rationale are server text: plain text only.
 */
export function ReviewTaskCard({task, onDecide}: ReviewTaskCardProps) {
  const headingId = useId();
  const [overriding, setOverriding] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | undefined>(undefined);
  const badge = verdictBadge({verdict: task.aiVerdict, verdictSource: 'ai'});

  async function send(decision: ReviewDecision) {
    setSending(true);
    setError(undefined);
    try {
      await onDecide(decision);
    } catch (caught: unknown) {
      setError(decisionErrorMessage(caught));
      setSending(false);
    }
  }

  return (
    <li
      aria-labelledby={headingId}
      className="flex flex-col gap-2 rounded-lg border p-3"
      data-review-task
    >
      <h3 id={headingId} className="font-medium break-words">
        <Link
          to={`/news/${task.itemId}`}
          className="underline-offset-4 hover:underline focus-visible:underline"
        >
          {task.headline}
        </Link>
      </h3>
      <p className="text-sm text-muted-foreground">
        <span className="font-mono">{task.vendorItemId}</span> ·{' '}
        {task.sourceDomain}
        {task.tickers.length > 0 && ` · ${task.tickers.join(', ')}`}
        {task.impact !== null &&
          ` · Market impact ${impactText(task.impact).toLowerCase()}`}
      </p>
      <p className="flex flex-wrap items-center gap-2 text-sm">
        <span>AI verdict:</span>
        {badge !== undefined && <RuleBadgeView badge={badge} />}
        <span>confidence {confidenceText(task.aiConfidence)}</span>
      </p>
      <p className="text-sm">
        Why it waits:{' '}
        {task.reasons.map(reviewReasonText).join(', ').toLowerCase()}.
        {task.ruleVerdict !== null && (
          <> Rules said {verdictText(task.ruleVerdict).toLowerCase()}</>
        )}
        {task.judgeVerdict !== null && (
          <>, the LLM judge {verdictText(task.judgeVerdict).toLowerCase()}</>
        )}
        {(task.ruleVerdict !== null || task.judgeVerdict !== null) && '.'}
      </p>
      {task.reasonCodes.length > 0 && (
        <p className="text-sm">
          Reason codes: {task.reasonCodes.map(reasonCodeText).join(', ')}
        </p>
      )}
      {task.rationale !== '' && (
        <p className="text-sm break-words">{task.rationale}</p>
      )}
      {error !== undefined && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {overriding ? (
        <OverrideForm
          aiVerdict={task.aiVerdict}
          sending={sending}
          onCancel={() => setOverriding(false)}
          onSubmit={(verdict, comment) =>
            send({action: 'override', verdict, comment})
          }
        />
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={sending}
            onClick={() => void send({action: 'approve'})}
          >
            Approve {verdictText(task.aiVerdict).toLowerCase()}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={sending}
            onClick={() => setOverriding(true)}
          >
            Change verdict…
          </Button>
        </div>
      )}
    </li>
  );
}

interface OverrideFormProps {
  aiVerdict: Verdict;
  sending: boolean;
  onCancel(): void;
  onSubmit(verdict: Verdict, comment: string): void;
}

function OverrideForm({
  aiVerdict,
  sending,
  onCancel,
  onSubmit,
}: OverrideFormProps) {
  const verdictId = useId();
  const commentId = useId();
  const problemId = useId();
  const [verdict, setVerdict] = useState<Verdict | ''>('');
  const [comment, setComment] = useState('');
  const [problem, setProblem] = useState<string | undefined>(undefined);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = overrideProblem(verdict, comment);
    setProblem(found);
    if (found === undefined && verdict !== '') {
      onSubmit(verdict, comment.trim());
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      aria-label="Change the verdict"
      className="flex flex-col gap-2"
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={verdictId}>New verdict</Label>
        <select
          id={verdictId}
          value={verdict}
          onChange={event => setVerdict(event.target.value as Verdict | '')}
          aria-describedby={problem === undefined ? undefined : problemId}
          className="h-8 w-48 rounded-lg border border-input bg-transparent px-2 text-sm"
        >
          <option value="">Choose…</option>
          {VERDICTS.filter(value => value !== aiVerdict).map(value => (
            <option key={value} value={value}>
              {verdictText(value)}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={commentId}>Why (required)</Label>
        <Textarea
          id={commentId}
          value={comment}
          onChange={event => setComment(event.target.value)}
          maxLength={1000}
          rows={3}
          aria-describedby={problem === undefined ? undefined : problemId}
        />
      </div>
      {problem !== undefined && (
        <p id={problemId} role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={sending}>
          {sending ? 'Saving…' : 'Save the new verdict'}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
