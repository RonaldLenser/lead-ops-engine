"""Lead Ops Engine backend: AI lead qualification with human approval."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lead-ops-engine")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
