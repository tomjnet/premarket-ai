import {screen, waitFor, within} from '@testing-library/react';
import {HttpResponse, http} from 'msw';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';

import {apiUrl} from '@/lib/env';
import {db} from '@/mocks/data/db';
import {server} from '@/mocks/node';
import {setScenario} from '@/mocks/scenarios';
import {expectNoA11yViolations} from '@/test/axe';
import {renderApp, withMockSession} from '@/test/render';

// Friday 2026-09-25, 09:00 in New York. Only Date is faked; timers are real.
const NOW = new Date('2026-09-25T13:00:00Z');
const WAIT = {timeout: 10_000};

beforeEach(() => {
  vi.useFakeTimers({toFake: ['Date']});
  vi.setSystemTime(NOW);
  withMockSession();
  db.chatTokenDelayMs = 2;
});

afterEach(() => {
  vi.useRealTimers();
  server.events.removeAllListeners();
});

async function openChat(path = '/chat') {
  const view = renderApp(path);
  await screen.findByRole('heading', {level: 1, name: 'Ask the News'}, WAIT);
  return view;
}

async function askQuestion(
  view: Awaited<ReturnType<typeof openChat>>,
  question: string,
) {
  await view.user.type(screen.getByLabelText('Your question'), question);
  await view.user.click(screen.getByRole('button', {name: 'Ask'}));
}

/** The conversation's last turn, once its answer has settled. */
async function settledTurn(): Promise<HTMLElement> {
  await waitFor(
    () =>
      expect(
        screen.queryByRole('button', {name: 'Answering…'}),
      ).not.toBeInTheDocument(),
    WAIT,
  );
  const turns = within(
    screen.getByRole('region', {name: 'Conversation'}),
  ).getAllByRole('article');
  const last = turns.at(-1);
  if (last === undefined) {
    throw new Error('No turn');
  }
  return last;
}

describe('ChatPage', {timeout: 30_000}, () => {
  it('is in the main navigation and says it is not advice', async () => {
    const {container} = await openChat();

    const nav = screen.getByRole('navigation', {name: 'Main'});
    expect(
      within(nav).getByRole('link', {name: 'Ask the News'}),
    ).toHaveAttribute('aria-current', 'page');
    expect(document.title).toBe('Ask the News · premarket-ai');
    expect(
      within(screen.getByRole('main')).getByText(
        'Decision support only, not investment advice.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('News date')).toHaveValue('2026-09-25');
    expect(screen.getByLabelText('Your question')).toHaveAttribute(
      'maxlength',
      '500',
    );
    await expectNoA11yViolations(container);
  });

  it('streams an answer, then shows it with citations and sources', async () => {
    db.chatTokenDelayMs = 30;
    let body: unknown;
    server.events.on('request:start', ({request}) => {
      if (request.url.endsWith('/api/chat')) {
        void request
          .clone()
          .json()
          .then(json => {
            body = json;
          });
      }
    });
    const view = await openChat();

    await askQuestion(view, 'What did Apple file?');

    // While answering: submit disabled, Cancel offered, live region busy.
    expect(
      await screen.findByRole('button', {name: 'Answering…'}),
    ).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Cancel'})).toBeInTheDocument();
    const live = screen
      .getByRole('region', {name: 'Conversation'})
      .querySelector('[aria-live="polite"]');
    expect(live).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByLabelText('Your question')).toHaveValue('');
    const turn = await settledTurn();
    expect(body).toEqual({
      question: 'What did Apple file?',
      date: '2026-09-25',
    });

    expect(live).toHaveAttribute('aria-busy', 'false');
    expect(
      within(turn).getByRole('heading', {
        name: 'Question: What did Apple file?',
      }),
    ).toBeInTheDocument();
    // The streamed text had a citation of a missing source ([7] is not
    // there); the final answer is the checked one.
    const answer = within(turn).getByText(/filed its latest quarterly results/);
    expect(answer.closest('p')?.textContent).not.toContain('[7]');
    const cite = within(turn).getByRole('button', {name: 'Source 1'});
    expect(cite).toHaveTextContent('[1]');

    const sources = within(turn).getByRole('list', {name: 'Sources'});
    const items = within(sources).getAllByRole('listitem');
    expect(items.length).toBeGreaterThanOrEqual(4);
    expect(
      within(items[0] as HTMLElement).getByText('SEC filing 8-K'),
    ).toBeInTheDocument();
    const external = within(items[0] as HTMLElement).getByRole('link');
    expect(external).toHaveAttribute('target', '_blank');
    expect(external.getAttribute('rel')).toContain('noopener');
    expect(external.getAttribute('rel')).toContain('noreferrer');
    expect(external.getAttribute('href')).toMatch(/^https:\/\/www\.sec\.gov\//);
    const vendor = items.find(item =>
      item.textContent?.includes('Vendor item (unverified)'),
    );
    expect(vendor).toBeDefined();
    expect(
      within(vendor as HTMLElement)
        .getByRole('link')
        .getAttribute('href'),
    ).toMatch(/^\/news\/\d+$/);
    expect(within(vendor as HTMLElement).getByRole('link')).not.toHaveAttribute(
      'target',
    );
    expect(
      within(turn).getByText(/^Model main-gpu4gb · prompt ask-v1/),
    ).toBeInTheDocument();

    await view.user.click(cite);
    expect(items[0]).toHaveFocus();
    await expectNoA11yViolations(view.container);
  });

  it('shows a refusal instead of an answer to an advice question', async () => {
    const view = await openChat();

    await askQuestion(view, 'Should I buy Apple today?');

    const turn = await settledTurn();
    const note = within(turn).getByRole('note');
    expect(within(note).getByText('No investment advice')).toBeInTheDocument();
    expect(
      within(note).getByText(/^I can't give investment advice\./),
    ).toBeInTheDocument();
    expect(
      within(turn).queryByRole('button', {name: /^Source/}),
    ).not.toBeInTheDocument();
  });

  it('keeps the conversation: one turn per question', async () => {
    const view = await openChat();

    await askQuestion(view, 'What did Apple file?');
    await settledTurn();
    await askQuestion(view, 'What did the Fed say?');
    await settledTurn();

    const turns = within(
      screen.getByRole('region', {name: 'Conversation'}),
    ).getAllByRole('article');
    expect(turns).toHaveLength(2);
    expect(
      within(turns[1] as HTMLElement).getByText(/Federal Reserve kept/),
    ).toBeInTheDocument();
  });

  it('shows the error event, without the half-streamed text', async () => {
    setScenario('chat-error');
    const view = await openChat();

    await askQuestion(view, 'What did Apple file?');

    const turn = await settledTurn();
    expect(within(turn).getByRole('alert')).toHaveTextContent(
      'No answerThe answer failed. Try again in a moment.',
    );
    expect(
      within(turn).queryByText(/Apple Inc\. filed/),
    ).not.toBeInTheDocument();
    expect(
      within(turn).queryByRole('list', {name: 'Sources'}),
    ).not.toBeInTheDocument();
  });

  it('explains 429 (one question at a time) and 503', async () => {
    setScenario('chat-busy');
    const view = await openChat();

    await askQuestion(view, 'What is new today?');
    expect(
      within(await settledTurn()).getByText(
        'Another question of yours is still being answered. Wait for it to finish, then ask again.',
      ),
    ).toBeInTheDocument();

    setScenario('chat-unavailable');
    await askQuestion(view, 'What is new today?');
    expect(
      within(await settledTurn()).getByText(
        "Ask the News isn't available on this server right now.",
      ),
    ).toBeInTheDocument();
  });

  it('checks the question before sending it', async () => {
    let requests = 0;
    server.events.on('request:start', ({request}) => {
      if (request.url.endsWith('/api/chat')) {
        requests += 1;
      }
    });
    const view = await openChat();

    await askQuestion(view, 'Hi');

    expect(
      screen.getByText('Write a question of at least 3 characters.'),
    ).toHaveAttribute('role', 'alert');
    expect(screen.getByLabelText('Your question')).toHaveAttribute(
      'aria-invalid',
      'true',
    );
    expect(requests).toBe(0);
  });

  it('cancels an answer', async () => {
    db.chatTokenDelayMs = 50;
    const view = await openChat();

    await askQuestion(view, 'What did Apple file?');
    await view.user.click(await screen.findByRole('button', {name: 'Cancel'}));

    const turn = await settledTurn();
    expect(
      within(turn).getByText('You stopped this answer.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Ask'})).toBeEnabled();
  });

  it('asks about the date in the URL', async () => {
    let body: unknown;
    server.use(
      http.post(apiUrl('/chat'), async ({request}) => {
        body = await request.json();
        return HttpResponse.json(
          {detail: 'Ask the News is not configured'},
          {
            status: 503,
          },
        );
      }),
    );
    const view = await openChat('/chat?date=2026-09-24');

    expect(screen.getByLabelText('News date')).toHaveValue('2026-09-24');
    await askQuestion(view, 'What is new?');
    await settledTurn();
    expect(body).toEqual({question: 'What is new?', date: '2026-09-24'});
  });
});
