import {Badge} from '@/components/ui/badge';

import type {BadgeTone, RuleBadge} from '../rules';

const VARIANTS = {
  danger: 'danger',
  warning: 'warning',
  neutral: 'outline',
} as const satisfies Record<BadgeTone, string>;

interface RuleBadgeViewProps {
  badge: RuleBadge;
}

/** One rule badge. The text carries the meaning; the colour only helps. */
export function RuleBadgeView({badge}: RuleBadgeViewProps) {
  return (
    <Badge variant={VARIANTS[badge.tone]} className="font-semibold">
      {badge.spokenText === undefined ? (
        badge.text
      ) : (
        <>
          <span aria-hidden="true">{badge.text}</span>
          <span className="sr-only">{badge.spokenText}</span>
        </>
      )}
    </Badge>
  );
}

interface RuleBadgesProps {
  badges: readonly RuleBadge[];
}

/** An item's rule badges, as a labelled list. Nothing when there are none. */
export function RuleBadges({badges}: RuleBadgesProps) {
  if (badges.length === 0) {
    return null;
  }
  return (
    <ul aria-label="Rule checks" className="flex flex-wrap gap-1.5">
      {badges.map(badge => (
        <li key={badge.key}>
          <RuleBadgeView badge={badge} />
        </li>
      ))}
    </ul>
  );
}
