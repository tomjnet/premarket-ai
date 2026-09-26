import {render, screen, within} from '@testing-library/react';
import {describe, expect, it} from 'vitest';

import {expectNoA11yViolations} from '@/test/axe';

import {RuleBadges} from './components/rule-badges';
import {
  dupTypeText,
  evidenceBadge,
  isFlagged,
  reasonCodeText,
  reasonCodeTone,
  ruleBadges,
  ruleRunSummary,
} from './rules';

const checked = {
  rulesChecked: true,
  reasonCodes: [] as string[],
  isDup: false,
  dupType: null,
  copies: 0,
};

describe('ruleBadges', () => {
  it('orders codes: FAKE COMPANY, FAKE TICKER, SPOOFED SOURCE, STALE, unknown', () => {
    const badges = ruleBadges({
      ...checked,
      // Sorted, as the backend sends them.
      reasonCodes: [
        'FABRICATED_CLAIM',
        'FAKE_COMPANY',
        'FAKE_TICKER',
        'SPOOFED_SOURCE',
        'STALE',
        'ZERO_DAY_CODE',
      ],
    });
    expect(badges.map(badge => [badge.text, badge.tone])).toEqual([
      ['FAKE COMPANY', 'danger'],
      ['FAKE TICKER', 'danger'],
      ['SPOOFED SOURCE', 'danger'],
      ['STALE', 'warning'],
      ['FABRICATED CLAIM', 'neutral'],
      ['ZERO DAY CODE', 'neutral'],
    ]);
  });

  it('places the AI run codes among the known ones', () => {
    const badges = ruleBadges({
      ...checked,
      // Rule codes sorted, then the AI run's, as the backend sends them.
      reasonCodes: [
        'FAKE_TICKER',
        'STALE',
        'UNSUPPORTED_LANGUAGE',
        'INJECTION_ATTEMPT',
        'NEW_CODE',
      ],
      isDup: true,
      dupType: 'paraphrase',
    });
    expect(badges.map(badge => [badge.text, badge.tone])).toEqual([
      ['FAKE TICKER', 'danger'],
      ['INJECTION ATTEMPT', 'danger'],
      ['STALE', 'warning'],
      ['UNSUPPORTED LANGUAGE', 'neutral'],
      ['NEW CODE', 'neutral'],
      ['DUPLICATE · paraphrase', 'neutral'],
    ]);
    expect(badges.at(-1)?.spokenText).toBe('Duplicate (paraphrase)');
  });

  it('shows no badge before the rules have checked the item', () => {
    expect(
      ruleBadges({
        ...checked,
        rulesChecked: false,
        reasonCodes: ['FAKE_TICKER'],
        copies: 3,
      }),
    ).toEqual([]);
  });

  it('ignores a repeated code', () => {
    expect(
      ruleBadges({...checked, reasonCodes: ['STALE', 'STALE']}),
    ).toHaveLength(1);
  });

  it('puts DUPLICATE ×N last on an original with copies', () => {
    const badges = ruleBadges(
      {...checked, reasonCodes: ['FAKE_TICKER'], copies: 3},
      'hidden',
    );
    expect(badges.at(-1)).toEqual({
      key: 'COPIES',
      text: 'DUPLICATE ×3',
      tone: 'neutral',
      spokenText: '3 copies of this story hidden',
    });
    expect(ruleBadges({...checked, copies: 1}, 'shown')[0]?.spokenText).toBe(
      '1 copy of this story shown',
    );
    expect(ruleBadges({...checked, copies: 2})[0]?.spokenText).toBe(
      '2 copies of this story',
    );
  });

  it('marks a duplicate with its match type', () => {
    const [badge] = ruleBadges({
      ...checked,
      isDup: true,
      dupType: 'near',
      copies: 0,
    });
    expect(badge).toMatchObject({
      text: 'DUPLICATE · near',
      spokenText: 'Duplicate (near copy)',
    });
    expect(ruleBadges({...checked, isDup: true, dupType: null})[0]?.text).toBe(
      'DUPLICATE',
    );
  });
});

describe('rule helpers', () => {
  it('turns codes into text and tones', () => {
    expect(reasonCodeText('SPOOFED_SOURCE')).toBe('SPOOFED SOURCE');
    expect(reasonCodeTone('FAKE_COMPANY')).toBe('danger');
    expect(reasonCodeTone('STALE')).toBe('warning');
    expect(reasonCodeTone('NO_CORROBORATION')).toBe('neutral');
    expect(dupTypeText('url')).toBe('same URL');
    expect(isFlagged({reasonCodes: []})).toBe(false);
    expect(isFlagged({reasonCodes: ['STALE']})).toBe(true);
  });

  it('labels evidence by its code, else by its check', () => {
    expect(
      evidenceBadge({check: 'source', code: 'SPOOFED_SOURCE', message: ''}),
    ).toEqual({key: 'SPOOFED_SOURCE', text: 'SPOOFED SOURCE', tone: 'danger'});
    expect(evidenceBadge({check: 'dedup', code: null, message: ''})).toEqual({
      key: 'dedup',
      text: 'DUPLICATE',
      tone: 'neutral',
    });
    expect(evidenceBadge({check: 'language', code: null, message: ''})).toEqual(
      {key: 'language', text: 'LANGUAGE CHECK', tone: 'neutral'},
    );
    expect(
      evidenceBadge({check: 'guard', code: 'INJECTION_ATTEMPT', message: ''}),
    ).toEqual({
      key: 'INJECTION_ATTEMPT',
      text: 'INJECTION ATTEMPT',
      tone: 'danger',
    });
  });
});

describe('ruleRunSummary', () => {
  const run = {finishedAt: null, items: 100, duplicates: 14, flagged: 17};

  it('describes every state of the rule run', () => {
    expect(ruleRunSummary(null)).toBe(
      "Rule checks haven't run for this date yet.",
    );
    expect(ruleRunSummary({...run, status: 'DONE'})).toBe(
      'Rule checks: 100 items · 14 duplicates · 17 flagged',
    );
    expect(ruleRunSummary({...run, status: 'RUNNING', items: 1})).toBe(
      'Rule checks are running: 1 item checked so far.',
    );
    expect(ruleRunSummary({...run, status: 'FAILED', items: 50})).toBe(
      'Rule checks failed after 50 items. Items marked "Not checked yet" have no rule badges.',
    );
  });
});

describe('RuleBadges', () => {
  it('lists the badges with names a screen reader can say', async () => {
    const {container} = render(
      <RuleBadges
        badges={ruleBadges(
          {...checked, reasonCodes: ['FAKE_TICKER', 'NEW_CODE'], copies: 3},
          'hidden',
        )}
      />,
    );

    const list = screen.getByRole('list', {name: 'Rule checks'});
    const items = within(list).getAllByRole('listitem');
    expect(items.map(item => item.textContent)).toEqual([
      'FAKE TICKER',
      'NEW CODE',
      'DUPLICATE ×33 copies of this story hidden',
    ]);
    expect(
      screen.getByText('3 copies of this story hidden'),
    ).toBeInTheDocument();
    expect(screen.getByText('DUPLICATE ×3')).toHaveAttribute(
      'aria-hidden',
      'true',
    );
    await expectNoA11yViolations(container);
  });

  it('renders nothing without badges', () => {
    const {container} = render(<RuleBadges badges={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
