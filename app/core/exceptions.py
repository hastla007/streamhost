"""Custom exception hierarchy for StreamHost."""
from __future__ import annotations


class StreamHostError(Exception):
    """Base exception for all StreamHost errors."""


class ConfigurationError(StreamHostError):
    """Configuration-related errors."""


class DatabaseError(StreamHostError):
    """Database operation errors."""


class StreamingError(StreamHostError):
    """Streaming pipeline errors."""


class MediaProcessingError(StreamHostError):
    """Media file processing errors."""


class ValidationError(StreamHostError):
    """Input validation errors."""


class RedisConnectionError(ConfigurationError):
    """Redis connection failed."""


class FFmpegError(StreamingError):
    """FFmpeg operation failed."""


class MetadataExtractionError(MediaProcessingError):
    """Failed to extract media metadata."""
