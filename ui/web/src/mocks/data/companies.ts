/**
 * Companies and sources of the synthetic vendor, the same lists as
 * vendor-sim (python/vendor-sim/src/vendor_sim/companies.py).
 */

export interface Company {
  ticker: string;
  /** Full legal name, for example `Apple Inc.`. */
  name: string;
  /** Name used in headlines, for example `Apple`. */
  short: string;
}

export const REAL_COMPANIES: readonly Company[] = [
  {ticker: 'AAPL', name: 'Apple Inc.', short: 'Apple'},
  {ticker: 'MSFT', name: 'Microsoft Corporation', short: 'Microsoft'},
  {ticker: 'NVDA', name: 'NVIDIA Corporation', short: 'NVIDIA'},
  {ticker: 'AMZN', name: 'Amazon.com, Inc.', short: 'Amazon'},
  {ticker: 'GOOGL', name: 'Alphabet Inc.', short: 'Alphabet'},
  {ticker: 'META', name: 'Meta Platforms, Inc.', short: 'Meta'},
  {ticker: 'AVGO', name: 'Broadcom Inc.', short: 'Broadcom'},
  {ticker: 'TSLA', name: 'Tesla, Inc.', short: 'Tesla'},
  {ticker: 'JPM', name: 'JPMorgan Chase & Co.', short: 'JPMorgan'},
  {ticker: 'LLY', name: 'Eli Lilly and Company', short: 'Eli Lilly'},
  {ticker: 'V', name: 'Visa Inc.', short: 'Visa'},
  {ticker: 'XOM', name: 'Exxon Mobil Corporation', short: 'Exxon Mobil'},
  {ticker: 'UNH', name: 'UnitedHealth Group Inc.', short: 'UnitedHealth'},
  {ticker: 'MA', name: 'Mastercard Incorporated', short: 'Mastercard'},
  {ticker: 'COST', name: 'Costco Wholesale Corporation', short: 'Costco'},
  {ticker: 'WMT', name: 'Walmart Inc.', short: 'Walmart'},
  {ticker: 'JNJ', name: 'Johnson & Johnson', short: 'Johnson & Johnson'},
  {
    ticker: 'PG',
    name: 'The Procter & Gamble Company',
    short: 'Procter & Gamble',
  },
  {ticker: 'HD', name: 'The Home Depot, Inc.', short: 'Home Depot'},
  {ticker: 'ORCL', name: 'Oracle Corporation', short: 'Oracle'},
];

/** Invented companies and tickers. */
export const FAKE_COMPANIES: readonly Company[] = [
  {ticker: 'QVXH', name: 'Quantavex Holdings Inc.', short: 'Quantavex'},
  {ticker: 'BRLQ', name: 'Borealiq Therapeutics Corp.', short: 'Borealiq'},
  {ticker: 'ZNTRA', name: 'Zentrality Energy Ltd.', short: 'Zentrality'},
  {ticker: 'KLVM', name: 'Kalvimo Semiconductor Inc.', short: 'Kalvimo'},
  {ticker: 'PXWD', name: 'Praxwood Financial Group', short: 'Praxwood'},
  {ticker: 'UMBX', name: 'Umbrix Robotics Corp.', short: 'Umbrix'},
];

/** The vendor's usual outlets. Reserved `.example` domains only. */
export const TRUSTED_DOMAINS: readonly string[] = [
  'wire.vendornews.example',
  'markets.dailybrief.example',
  'newsdesk.finwire.example',
  'press.marketline.example',
];

/** Low-quality outlets the vendor pads the feed with. */
export const LOW_QUALITY_DOMAINS: readonly string[] = [
  'stockbuzz-alerts.example',
  'pennyrocket.example',
  'hot-tickers.example',
];

/** Lookalikes of real outlets, always on the reserved `.test` TLD. */
export const SPOOFED_DOMAINS: readonly string[] = [
  'reuters-news.test',
  'bloomberg-markets.test',
  'cnbc-alerts.test',
  'wsj-finance.test',
];
