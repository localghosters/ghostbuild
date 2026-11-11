"""Exceptions that GhostBuild reports to the user as clean error messages."""

from __future__ import annotations


class GhostBuildError(Exception):
    """Base class for errors that are shown to the user without a traceback."""


class PathError(GhostBuildError):
    """A path is missing, of the wrong type, or otherwise unusable."""


class ConfigError(GhostBuildError):
    """The configuration file is invalid."""


class UnsupportedProjectError(GhostBuildError):
    """No build adapter recognises the project."""


class PrerequisiteError(GhostBuildError):
    """A tool required to run the build is missing."""


class IsolationError(GhostBuildError):
    """The requested isolation mode cannot be provided."""


class LocalFallbackNotApproved(IsolationError):
    """Docker is unavailable and the user has not approved a local rebuild."""


class ArchiveError(GhostBuildError):
    """An archive could not be inspected."""


class UnsafeArchiveError(ArchiveError):
    """An archive contains a member path that could escape its directory."""


class UnsafeDeletionError(GhostBuildError):
    """GhostBuild refused to delete a directory it did not create."""


class ReportError(GhostBuildError):
    """A stored result could not be read or rendered."""
