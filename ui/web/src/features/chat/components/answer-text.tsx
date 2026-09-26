import {answerSegments} from '../chat';

interface AnswerTextProps {
  text: string;
  /** Source numbers that exist; other markers stay plain text. */
  sourceNumbers: ReadonlySet<number>;
  /** Moves focus to source `n` in the list below the answer. */
  onCite(n: number): void;
}

/**
 * An answer with its citation markers as buttons to the numbered sources.
 * The text is model output: rendered as text nodes, never as HTML.
 */
export function AnswerText({text, sourceNumbers, onCite}: AnswerTextProps) {
  return (
    <p className="leading-relaxed break-words whitespace-pre-line">
      {answerSegments(text, sourceNumbers).map((segment, index) =>
        segment.kind === 'text' ? (
          <span key={index}>{segment.text}</span>
        ) : (
          <button
            key={index}
            type="button"
            onClick={() => onCite(segment.n)}
            // "[2]" reads badly; the name keeps the visible number.
            aria-label={`Source ${segment.n}`}
            className="mx-0.5 rounded-sm px-0.5 align-baseline text-sm font-medium text-primary underline underline-offset-2 hover:bg-muted"
          >
            [{segment.n}]
          </button>
        ),
      )}
    </p>
  );
}
