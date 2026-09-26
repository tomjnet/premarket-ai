"""Duplicate check of vendor items: L0 URL, L1 exact hash, L2 SimHash.

Runs before any LLM work (increment 2). Redis holds a rebuildable 7-day index;
Postgres (``ai.duplicate_link``) holds the decisions.
"""
