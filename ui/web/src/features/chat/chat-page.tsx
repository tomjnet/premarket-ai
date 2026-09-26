import {useId, useState} from 'react';
import type {FormEvent, KeyboardEvent} from 'react';
import {useSearchParams} from 'react-router';

import {QUESTION_MAX_CHARS} from '@/api/schemas/chat';
import {useDocumentTitle} from '@/components/layout/use-document-title';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {Label} from '@/components/ui/label';
import {Textarea} from '@/components/ui/textarea';
import {isIsoDate, todayInNewYork} from '@/lib/time';

import {questionProblem} from './chat';
import {ChatTurnView} from './components/chat-turn';
import {useAskNews} from './hooks/use-ask-news';

/**
 * `/chat`: "Ask the News". Questions are answered from SEC filings,
 * Federal Reserve and SEC releases and the date's vendor items, with
 * numbered citations. The conversation lives in this page only.
 */
export function ChatPage() {
  useDocumentTitle('Ask the News');
  const [searchParams] = useSearchParams();
  const today = todayInNewYork();
  const questionId = useId();
  const hintId = useId();
  const problemId = useId();
  const dateId = useId();
  const [question, setQuestion] = useState('');
  const [date, setDate] = useState(() => {
    const fromUrl = searchParams.get('date');
    return fromUrl !== null && isIsoDate(fromUrl) && fromUrl <= today
      ? fromUrl
      : today;
  });
  const [problem, setProblem] = useState<string | undefined>(undefined);
  const {turns, ask, cancel, answering} = useAskNews();

  function submit() {
    if (answering) {
      return;
    }
    const found = questionProblem(question);
    setProblem(found);
    if (found !== undefined) {
      return;
    }
    const day = isIsoDate(date) ? date : today;
    setQuestion('');
    void ask(question.trim(), day);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submit();
  }

  // Ctrl+Enter (or Cmd+Enter) sends; Enter alone starts a new line.
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      submit();
    }
  }

  const describedBy = problem === undefined ? hintId : `${hintId} ${problemId}`;
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Ask the News</h1>
        <p className="text-muted-foreground">
          Answers come from SEC filings, Federal Reserve and SEC releases, and
          the vendor's items of the chosen date (unverified). Each answer cites
          its sources by number.
        </p>
        <p className="text-sm font-medium">
          Decision support only, not investment advice.
        </p>
      </div>
      <form
        onSubmit={handleSubmit}
        noValidate
        className="flex flex-col gap-3 rounded-lg border p-3"
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={questionId}>Your question</Label>
          <Textarea
            id={questionId}
            value={question}
            maxLength={QUESTION_MAX_CHARS}
            rows={3}
            onChange={event => {
              setQuestion(event.target.value);
              setProblem(undefined);
            }}
            onKeyDown={handleKeyDown}
            aria-invalid={problem !== undefined}
            aria-describedby={describedBy}
          />
          <p id={hintId} className="text-xs text-muted-foreground">
            3 to {QUESTION_MAX_CHARS} characters ({[...question].length} used).
            Ctrl+Enter sends.
          </p>
          {problem !== undefined && (
            <p id={problemId} role="alert" className="text-sm text-destructive">
              {problem}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={dateId}>News date</Label>
            <Input
              id={dateId}
              type="date"
              value={date}
              max={today}
              onChange={event => setDate(event.target.value)}
              className="w-auto"
            />
          </div>
          <Button type="submit" disabled={answering}>
            {answering ? 'Answering…' : 'Ask'}
          </Button>
          {answering && (
            <Button type="button" variant="outline" onClick={cancel}>
              Cancel
            </Button>
          )}
        </div>
      </form>
      {turns.length > 0 && (
        <section aria-label="Conversation" className="flex flex-col gap-4">
          {turns.map(turn => (
            <ChatTurnView key={turn.id} turn={turn} />
          ))}
        </section>
      )}
    </div>
  );
}
