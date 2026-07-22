"""Shared crawler exception hierarchy."""

from __future__ import annotations


class CrawlerError(Exception):
    """Base exception for expected crawler failures."""


class SourceError(CrawlerError):
    """A remote source could not be fetched or returned an invalid response."""


class SchemaError(CrawlerError):
    """A response did not match the supported source schema."""


class ValidationError(CrawlerError):
    """Normalized data failed a required integrity check."""


class QuarantinedGameError(ValidationError):
    """A game was stored but cannot be published as validated data."""

