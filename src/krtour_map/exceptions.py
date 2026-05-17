from __future__ import annotations


class KrtourMapError(Exception):
    """Base exception for krtour-map."""


class DuplicateFeatureError(KrtourMapError):
    """Raised when a feature already exists and create-only semantics were requested."""


class FeatureNotFoundError(KrtourMapError):
    """Raised when a feature is required but missing."""


class SourceRecordNotFoundError(KrtourMapError):
    """Raised when a source record is required but missing."""


class FixtureAssertionError(AssertionError):
    """Raised when a fixture replay assertion fails."""
