"""Deterministic rule checks (increment 2): no LLM anywhere.

Duplicates (``ai_api.dedup``), fake companies and tickers (SEC registry),
spoofed sources and stale news. Hard rules decide first; the LLM judge of
increment 4 can't override FAKE_COMPANY or FAKE_TICKER.
"""
