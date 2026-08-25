"""Escalation channel: bounded agents for items the deterministic loop cannot
digest (placeholder).

Agents receive ``needs_agent`` items, attempt repairs, and either hand items
back to the main loop or mark them ``needs_human``. They are deliberately
**outside** the main flow (ARCHITECTURE.md sections 2.2 and 3) and deferred
to Part 6; nothing is implemented in the first batch.
"""
