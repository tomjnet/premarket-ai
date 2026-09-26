import {Alert, AlertDescription, AlertTitle} from '@/components/ui/alert';
import {formatLongDate} from '@/lib/time';

import type {ChatTurn} from '../hooks/use-ask-news';

import {AnswerText} from './answer-text';
import {SourceList} from './source-list';

interface ChatTurnViewProps {
  turn: ChatTurn;
}

/**
 * One question and its answer: the text as it streams, then the checked
 * answer with citation buttons, notes about it, and the numbered sources.
 */
export function ChatTurnView({turn}: ChatTurnViewProps) {
  const sources = turn.sources?.sources ?? [];
  const numbers = new Set(sources.map(source => source.n));
  const sourceId = (n: number) => `turn-${turn.id}-source-${n}`;
  const focusSource = (n: number) => {
    document.getElementById(sourceId(n))?.focus();
  };
  const done = turn.done;
  return (
    <article
      aria-labelledby={`turn-${turn.id}-question`}
      className="flex flex-col gap-3 border-t pt-4"
    >
      <h2 id={`turn-${turn.id}-question`} className="font-semibold break-words">
        <span className="sr-only">Question:</span> {turn.question}
      </h2>
      <p className="text-xs text-muted-foreground">
        News of {formatLongDate(turn.date)}
      </p>
      {/* Polite and busy while streaming: screen readers read the answer
          once it is complete instead of every token. */}
      <div
        aria-live="polite"
        aria-busy={turn.status === 'answering'}
        className="flex flex-col gap-2"
      >
        {turn.status === 'answering' && (
          <p className="leading-relaxed break-words whitespace-pre-line">
            {turn.streamed === '' ? (
              <span className="text-muted-foreground">
                {turn.sources === undefined
                  ? 'Searching the sources…'
                  : 'Writing the answer…'}
              </span>
            ) : (
              turn.streamed
            )}
          </p>
        )}
        {done !== undefined && done.refused && (
          <Alert role="note">
            <AlertTitle>No investment advice</AlertTitle>
            <AlertDescription>
              <AnswerText
                text={done.answer}
                sourceNumbers={numbers}
                onCite={focusSource}
              />
            </AlertDescription>
          </Alert>
        )}
        {done !== undefined && !done.refused && (
          <AnswerText
            text={done.answer}
            sourceNumbers={numbers}
            onCite={focusSource}
          />
        )}
        {turn.status === 'failed' && (
          <Alert variant="destructive">
            <AlertTitle>No answer</AlertTitle>
            <AlertDescription>{turn.error}</AlertDescription>
          </Alert>
        )}
        {turn.status === 'cancelled' && (
          <p className="text-sm text-muted-foreground">
            You stopped this answer.
          </p>
        )}
      </div>
      {done !== undefined && <AnswerNotes done={done} />}
      {turn.sources !== undefined && turn.status !== 'failed' && (
        <section
          aria-labelledby={`turn-${turn.id}-sources`}
          className="flex flex-col gap-2"
        >
          <h3 id={`turn-${turn.id}-sources`} className="text-sm font-semibold">
            Sources
          </h3>
          <SourceList
            sources={sources}
            cited={done?.citations}
            sourceId={sourceId}
          />
        </section>
      )}
    </article>
  );
}

interface AnswerNotesProps {
  done: NonNullable<ChatTurn['done']>;
}

/** What the reader should know about a finished answer. */
function AnswerNotes({done}: AnswerNotesProps) {
  const notes: string[] = [];
  if (done.injectionFlagged) {
    notes.push(
      'Part of the question looked like instructions to the model; it was treated as plain text.',
    );
  }
  if (!done.refused && done.citations.length === 0) {
    notes.push('This answer cites no source: check it before relying on it.');
  } else if (!done.refused && !done.citesTrusted) {
    notes.push(
      'This answer cites only vendor items, which are unverified. No filing or official release backs it.',
    );
  }
  return (
    <div className="flex flex-col gap-1 text-sm">
      {notes.map(note => (
        <p key={note} className="font-medium">
          {note}
        </p>
      ))}
      <p className="text-xs text-muted-foreground">
        Model {done.model} · prompt {done.promptVersion} ·{' '}
        {(done.elapsedMs / 1000).toFixed(1)} s
      </p>
    </div>
  );
}
