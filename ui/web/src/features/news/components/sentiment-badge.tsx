import {Minus, TrendingDown, TrendingUp} from 'lucide-react';

import type {Sentiment} from '@/api/schemas/news';
import {Badge} from '@/components/ui/badge';

import {sentimentText} from '../ai';

const ICONS = {
  bullish: TrendingUp,
  neutral: Minus,
  bearish: TrendingDown,
} as const satisfies Record<Sentiment, unknown>;

interface SentimentBadgeProps {
  sentiment: Sentiment;
}

/**
 * The AI summary's sentiment. The words carry the meaning (no colour); the
 * icon only helps.
 */
export function SentimentBadge({sentiment}: SentimentBadgeProps) {
  const Icon = ICONS[sentiment];
  return (
    <Badge variant="outline" data-sentiment={sentiment}>
      <Icon aria-hidden="true" />
      Sentiment: {sentimentText(sentiment).toLowerCase()}
    </Badge>
  );
}
