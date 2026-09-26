import type {
  ChatDoneWire,
  ChatSourceWire,
  ChatSourcesWire,
} from '@/api/schemas/chat';
import type {NewsDetailWire} from '@/api/schemas/news';
import {addDays, previousTradingDate} from '@/lib/time';

import {REAL_COMPANIES} from './companies';
import type {Company} from './companies';

/**
 * The mock's "Ask the News" (increment 3): a canned answer from a small
 * synthetic trusted corpus plus the day's vendor items, with the same
 * events, citation rules and refusal as the backend's answer chain.
 */

export const CHAT_MODEL = 'main-gpu4gb';
export const CHAT_PROMPT_VERSION = 'ask-v1';
/** At most this many vendor items are offered as sources. */
const VENDOR_MAX = 2;
const SNIPPET_CHARS = 200;

const ADVICE = /\b(?:buy|sell|hold|price target|should i|invest in)\b/i;
const INJECTION = /ignore (?:all |any )?(?:previous|prior) instructions/i;

/** The backend's answer when a question asks for investment advice. */
export const REFUSAL =
  "I can't give investment advice. Here is what the sources say instead.";

/** Everything the mock streams for one question. */
export interface MockAnswer {
  sources: ChatSourcesWire;
  /** The model's raw text, streamed as `token` events. */
  tokens: string[];
  done: ChatDoneWire;
}

function snippet(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  const chars = [...flat];
  if (chars.length <= SNIPPET_CHARS) {
    return flat;
  }
  return `${chars
    .slice(0, SNIPPET_CHARS - 1)
    .join('')
    .trimEnd()}…`;
}

/** The companies a question names, by ticker or short name. */
export function companiesIn(question: string): Company[] {
  return REAL_COMPANIES.filter(company => {
    const ticker = new RegExp(`\\b${company.ticker}\\b`);
    const name = new RegExp(`\\b${company.short}\\b`, 'i');
    return ticker.test(question) || name.test(question);
  });
}

function edgarUrl(ticker: string): string {
  return `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${ticker}&type=8-K`;
}

/** The synthetic trusted sources for a question (numbers not set yet). */
function trustedSources(
  companies: readonly Company[],
  date: string,
): Array<Omit<ChatSourceWire, 'n'>> {
  const filed = previousTradingDate(addDays(date, -6));
  const [company] = companies;
  if (company === undefined) {
    return [
      {
        kind: 'fed_press',
        trusted: true,
        title: '[SYNTHETIC] Federal Reserve issues FOMC statement',
        url: 'https://www.federalreserve.gov/newsevents/pressreleases.htm',
        published_at: filed,
        ticker: null,
        snippet:
          'The Committee decided to maintain the target range for the federal funds rate and will continue to monitor incoming information. (Synthetic text for the mock.)',
      },
      {
        kind: 'sec_press',
        trusted: true,
        title: '[SYNTHETIC] SEC charges operators of a stock promotion scheme',
        url: 'https://www.sec.gov/newsroom/press-releases',
        published_at: filed,
        ticker: null,
        snippet:
          'The Securities and Exchange Commission charged the operators of websites that spread false news about small companies. (Synthetic text for the mock.)',
      },
    ];
  }
  return [
    {
      kind: 'edgar_8k',
      trusted: true,
      title: `[SYNTHETIC] ${company.name} 8-K: Results of Operations and Financial Condition`,
      url: edgarUrl(company.ticker),
      published_at: filed,
      ticker: company.ticker,
      snippet: `${company.name} furnished its quarterly results as Exhibit 99.1. Revenue and earnings per share are reported in the exhibit. (Synthetic text for the mock.)`,
    },
    {
      kind: 'edgar_ex99',
      trusted: true,
      title: `[SYNTHETIC] ${company.name} press release (EX-99.1)`,
      url: edgarUrl(company.ticker),
      published_at: filed,
      ticker: company.ticker,
      snippet: `${company.short} reported quarterly revenue up from a year earlier and kept its full-year outlook. (Synthetic text for the mock.)`,
    },
    {
      kind: 'xbrl_facts',
      trusted: true,
      title: `[SYNTHETIC] ${company.name} company facts (XBRL)`,
      url: `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${company.ticker}`,
      published_at: null,
      ticker: company.ticker,
      snippet: `Revenues, net income and shares outstanding as filed by ${company.short}. (Synthetic text for the mock.)`,
    },
  ];
}

function vendorSources(
  companies: readonly Company[],
  items: readonly NewsDetailWire[],
): Array<Omit<ChatSourceWire, 'n'>> {
  const tickers = new Set(companies.map(company => company.ticker));
  return items
    .filter(
      item => !item.is_dup && item.tickers.some(ticker => tickers.has(ticker)),
    )
    .slice(0, VENDOR_MAX)
    .map(item => ({
      kind: 'vendor',
      trusted: false,
      title: `Vendor item ${item.vendor_item_id}: ${item.headline}`,
      url: `/news/${item.id}`,
      published_at: item.feed_date,
      ticker: item.tickers[0] ?? null,
      snippet: snippet(item.body),
    }));
}

/** Text split into small pieces, as a model streams it. */
function toTokens(text: string): string[] {
  return text.match(/\S+\s*/g) ?? [];
}

/**
 * The mock answer to `question` about the news of `date`, whose vendor
 * items are `items` (newest first).
 */
export function mockAnswer(
  question: string,
  items: readonly NewsDetailWire[],
  date: string,
): MockAnswer {
  const companies = companiesIn(question).slice(0, 1);
  const numbered = [
    ...trustedSources(companies, date),
    ...vendorSources(companies, items),
  ].map((source, index) => ({...source, n: index + 1}));
  const [company] = companies;
  const vendor = numbered.find(source => !source.trusted);
  let text: string;
  if (company === undefined) {
    text =
      'The Federal Reserve kept its policy rate unchanged at its last meeting [1]. ' +
      'The SEC recently charged people who spread false stock news online [2], ' +
      'a reminder to check vendor stories against filings [7].';
  } else {
    text =
      `${company.name} filed its latest quarterly results on an 8-K [1], ` +
      'and its press release says revenue grew from a year earlier [2][3][9]. ';
    if (vendor !== undefined) {
      text += `The vendor reports a newer story about ${company.short} [${vendor.n}], which no filing confirms yet.`;
    } else {
      text += `No vendor item for ${date} mentions ${company.short}.`;
    }
  }
  // The model's text may cite a source that doesn't exist ([7], [9]):
  // `done` has it removed, like the backend's citation check.
  const valid = new Set(numbered.map(source => source.n));
  const cited: number[] = [];
  const answer = text
    .replace(/\[(\d+)\]/g, (marker, n: string) => {
      const number = Number(n);
      if (!valid.has(number)) {
        return '';
      }
      if (!cited.includes(number)) {
        cited.push(number);
      }
      return marker;
    })
    .replace(/ {2,}/g, ' ')
    .replace(/ ([,.])/g, '$1')
    .trim();
  const refused = ADVICE.test(question);
  const trusted = new Set(
    numbered.filter(source => source.trusted).map(source => source.n),
  );
  const citations = refused ? [] : cited;
  return {
    sources: {sources: numbered, reranked: true},
    tokens: toTokens(text),
    done: {
      answer: refused ? REFUSAL : answer,
      citations,
      cites_trusted: citations.some(n => trusted.has(n)),
      refused,
      injection_flagged: INJECTION.test(question),
      model: CHAT_MODEL,
      prompt_version: CHAT_PROMPT_VERSION,
      elapsed_ms: 1800 + [...question].length * 7,
    },
  };
}
