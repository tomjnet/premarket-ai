import {render, screen} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {expectNoA11yViolations} from '@/test/axe';

import {aiRunSummary, aiStatusText, sentimentText} from './ai';
import {SentimentBadge} from './components/sentiment-badge';

describe('aiRunSummary', () => {
  const run = {
    finishedAt: null,
    items: 86,
    paraphrases: 3,
    conflicts: 0,
    summarized: 68,
    fallbacks: 0,
    failed: 0,
    model: 'main-gpu4gb',
  };

  it('describes every state of the AI run', () => {
    expect(aiRunSummary(null)).toBe(
      "AI summaries haven't run for this date yet.",
    );
    expect(aiRunSummary({...run, status: 'DONE'})).toBe(
      'AI: 68 summarized · 3 paraphrases',
    );
    expect(
      aiRunSummary({
        ...run,
        status: 'DONE',
        paraphrases: 1,
        conflicts: 2,
        fallbacks: 1,
        failed: 4,
      }),
    ).toBe(
      'AI: 68 summarized · 1 paraphrase · 1 lead sentence used · 4 failed',
    );
    expect(aiRunSummary({...run, status: 'RUNNING', summarized: 10})).toBe(
      'AI summaries are running: 10 summarized so far.',
    );
    expect(aiRunSummary({...run, status: 'FAILED'})).toBe(
      'The AI run failed after 68 summaries. Items without a summary show their excerpt.',
    );
  });
});

describe('AI texts', () => {
  it('names sentiments and statuses', () => {
    expect(sentimentText('bearish')).toBe('Bearish');
    expect(aiStatusText('DONE')).toBe('Summarized');
    expect(aiStatusText('SKIPPED')).toMatch(/^Skipped/);
  });
});

describe('SentimentBadge', () => {
  it('says the sentiment in words, not only with an icon or colour', async () => {
    const {container} = render(<SentimentBadge sentiment="bearish" />);

    const badge = screen.getByText('Sentiment: bearish');
    expect(badge).toHaveAttribute('data-sentiment', 'bearish');
    expect(badge.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    await expectNoA11yViolations(container);
  });
});
