-- premarket-ai: legacy company master (increment 0).
-- The same companies vendor-sim writes real and misleading news about
-- (python/vendor-sim/src/vendor_sim/companies.py). Invented companies used by
-- FAKE items are deliberately absent.

INSERT INTO legacy.companies (ticker, name, sector) VALUES
  ('AAPL',  'Apple Inc.',                    'Information Technology'),
  ('MSFT',  'Microsoft Corporation',         'Information Technology'),
  ('NVDA',  'NVIDIA Corporation',            'Information Technology'),
  ('AMZN',  'Amazon.com, Inc.',              'Consumer Discretionary'),
  ('GOOGL', 'Alphabet Inc.',                 'Communication Services'),
  ('META',  'Meta Platforms, Inc.',          'Communication Services'),
  ('AVGO',  'Broadcom Inc.',                 'Information Technology'),
  ('TSLA',  'Tesla, Inc.',                   'Consumer Discretionary'),
  ('JPM',   'JPMorgan Chase & Co.',          'Financials'),
  ('LLY',   'Eli Lilly and Company',         'Health Care'),
  ('V',     'Visa Inc.',                     'Financials'),
  ('XOM',   'Exxon Mobil Corporation',       'Energy'),
  ('UNH',   'UnitedHealth Group Inc.',       'Health Care'),
  ('MA',    'Mastercard Incorporated',       'Financials'),
  ('COST',  'Costco Wholesale Corporation',  'Consumer Staples'),
  ('WMT',   'Walmart Inc.',                  'Consumer Staples'),
  ('JNJ',   'Johnson & Johnson',             'Health Care'),
  ('PG',    'The Procter & Gamble Company',  'Consumer Staples'),
  ('HD',    'The Home Depot, Inc.',          'Consumer Discretionary'),
  ('ORCL',  'Oracle Corporation',            'Information Technology')
ON CONFLICT (ticker) DO NOTHING;
