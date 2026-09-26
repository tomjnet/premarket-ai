import {WATCHLIST_MAX_TICKERS} from '@/api/schemas/brief';

/** A ticker as the backend accepts it (`BRK.B` too). */
const TICKER = /^[A-Z][A-Z0-9.-]{0,9}$/;

/**
 * The tickers of the form's text (commas or spaces between them), upper
 * cased, without repeats; or the first problem. The backend checks them
 * against the SEC registry.
 */
export function parseTickers(
  text: string,
): {tickers: string[]} | {problem: string} {
  const tickers: string[] = [];
  for (const raw of text.split(/[\s,;]+/)) {
    if (raw === '') {
      continue;
    }
    const ticker = raw.toUpperCase();
    if (!TICKER.test(ticker)) {
      return {problem: `"${raw.slice(0, 20)}" is not a ticker.`};
    }
    if (!tickers.includes(ticker)) {
      tickers.push(ticker);
    }
  }
  if (tickers.length > WATCHLIST_MAX_TICKERS) {
    return {problem: `Follow at most ${WATCHLIST_MAX_TICKERS} tickers.`};
  }
  return {tickers};
}
