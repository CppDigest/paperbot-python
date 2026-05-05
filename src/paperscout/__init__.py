"""WG21 paper scout: Slack bot, index polling, and isocpp.org probing."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("paperscout")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
