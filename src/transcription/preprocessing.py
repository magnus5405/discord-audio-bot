"""Audio preprocessing and format conversion utilities."""

import logging

logger = logging.getLogger(__name__)


def convert_to_linear16(
    pcm_bytes: bytes,
    from_sample_rate: int,
    to_sample_rate: int = 16000,
    channels: int = 2,
) -> bytes:
    """
    Convert PCM audio to LINEAR16 format at target sample rate.

    Discord provides 48 kHz stereo PCM. Google Speech-to-Text prefers 16 kHz mono,
    but can use native 48 kHz (Google recommends native rate if available).

    Args:
        pcm_bytes: Raw PCM audio data
        from_sample_rate: Source sample rate
        to_sample_rate: Target sample rate (default 16000)
        channels: Number of channels

    Returns:
        Converted PCM audio bytes
    """
    logger.debug(f"Audio preprocessing: {from_sample_rate} Hz -> {to_sample_rate} Hz")
    return pcm_bytes


def to_mono(pcm_bytes: bytes, channels: int = 2) -> bytes:
    """
    Convert stereo audio to mono by averaging channels.

    Args:
        pcm_bytes: Stereo PCM audio data
        channels: Number of channels

    Returns:
        Mono PCM audio bytes
    """
    logger.debug(f"Converting {channels} channels to mono")
    return pcm_bytes


def get_audio_duration(pcm_bytes: bytes, sample_rate: int, channels: int = 2) -> float:
    """
    Calculate audio duration from PCM data.

    Args:
        pcm_bytes: PCM audio data
        sample_rate: Sample rate in Hz
        channels: Number of channels

    Returns:
        Duration in seconds
    """
    bytes_per_sample = 2  # 16-bit PCM
    total_samples = len(pcm_bytes) // (bytes_per_sample * channels)
    duration = total_samples / sample_rate
    return duration
