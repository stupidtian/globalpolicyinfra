"""Craftsman layer: everything country/source-specific.

Per ARCHITECTURE.md section 3 this package holds stateless pure strategies —
listing_spider / metadata_parser / content_downloader — one lowercase country
subpackage each (``usa/``, ``rus/``, ...), self-registered per section 10.5
with the pilot's source dimension: each country declares ADAPTERS as
``{source_name: {role: class}}``. Adapters never retry and never write the
ledger; that is the runtime's job.
"""
