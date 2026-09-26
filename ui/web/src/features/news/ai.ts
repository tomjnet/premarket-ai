import type {AiDetail, AiRun, Sentiment} from '@/api/schemas/news';

/**
 * What the first AI run (increment 3) adds: a one-line summary and its
 * sentiment per unique item, extracted companies and claims, and the run's
 * counts. Sentiment describes the story's tone, never advice.
 */

const SENTIMENT_TEXT: Record<Sentiment, string> = {
  bullish: 'Bullish',
  neutral: 'Neutral',
  bearish: 'Bearish',
};

const STATUS_TEXT: Record<AiDetail['status'], string> = {
  DONE: 'Summarized',
  SKIPPED: 'Skipped (not sent to the model)',
  DUPLICATE: 'Not summarized: a paraphrase of an earlier story',
  FAILED: "Failed: the model couldn't process this item",
};

/** `bullish` → `Bullish`. */
export function sentimentText(sentiment: Sentiment): string {
  return SENTIMENT_TEXT[sentiment];
}

/** What the AI run did with an item, in words. */
export function aiStatusText(status: AiDetail['status']): string {
  return STATUS_TEXT[status];
}

function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

/**
 * The feed header's line about the date's AI run, for example
 * `AI: 82 summarized · 2 paraphrases`. (`conflicts` isn't shown: a
 * conflicting version is evidence on its item, not a flag.)
 */
export function aiRunSummary(aiRun: AiRun | null): string {
  if (aiRun === null) {
    return "AI summaries haven't run for this date yet.";
  }
  if (aiRun.status === 'RUNNING') {
    return `AI summaries are running: ${aiRun.summarized} summarized so far.`;
  }
  if (aiRun.status === 'FAILED') {
    return `The AI run failed after ${aiRun.summarized} summaries. Items without a summary show their excerpt.`;
  }
  const parts = [
    `AI: ${aiRun.summarized} summarized`,
    plural(aiRun.paraphrases, 'paraphrase'),
  ];
  if (aiRun.fallbacks > 0) {
    parts.push(`${plural(aiRun.fallbacks, 'lead sentence')} used`);
  }
  if (aiRun.failed > 0) {
    parts.push(`${aiRun.failed} failed`);
  }
  return parts.join(' · ');
}
