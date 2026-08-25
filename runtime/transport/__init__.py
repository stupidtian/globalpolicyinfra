"""Transport layer: how requests actually reach the outside world.

HTTP today (:mod:`runtime.transport.http`); a browser transport
(Playwright + the action vocabulary) is a planned component — see
ARCHITECTURE.md section 6.6.
"""

from runtime.transport.http import HttpTransport

__all__ = ["HttpTransport"]
