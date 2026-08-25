"""Constitution layer: data models, state model, path and config contracts.

This package performs no execution and carries no heavy dependencies
(ARCHITECTURE.md section 3).
"""

from core.config import (
    ConfigError,
    load_config,
    resolve_data_root,
    write_config,
)
from core.country import Country
from core.document import Document, DocumentRecord, compute_doc_id
from core.state import Status, is_terminal

__all__ = [
    "ConfigError",
    "Country",
    "Document",
    "DocumentRecord",
    "Status",
    "compute_doc_id",
    "is_terminal",
    "load_config",
    "resolve_data_root",
    "write_config",
]
