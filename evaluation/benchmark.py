"""Benchmark definitions and evaluation utilities."""

from pathlib import Path


class PolicyBench:
    """Placeholder for a cross-country policy extraction benchmark."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def load(self) -> None:
        """Load benchmark data."""
        raise NotImplementedError("PolicyBench is under design.")
