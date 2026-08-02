"""Tests for dashboard formatting helpers."""

import math

from src.ui.dashboard.formatting import format_stt_minutes_with_price


def test_format_stt_minutes_with_price_shows_google_estimate_by_default() -> None:
    assert format_stt_minutes_with_price(2.5, 0.016) == "2.50 min ($0.04)"


def test_format_stt_minutes_with_price_suppresses_google_cost_for_local_provider() -> None:
    assert format_stt_minutes_with_price(2.5, 0.016, provider="local") == "2.50 min (avg --)"


def test_format_stt_minutes_with_price_shows_average_local_inference_when_available() -> None:
    assert (
        format_stt_minutes_with_price(
            2.5,
            0.016,
            provider="local",
            average_inference_seconds=1.375,
        )
        == "2.50 min (avg 1.38s)"
    )


def test_format_stt_minutes_with_price_ignores_invalid_local_average_values() -> None:
    assert (
        format_stt_minutes_with_price(
            2.5,
            0.016,
            provider="local",
            average_inference_seconds="n/a",
        )
        == "2.50 min (avg --)"
    )


def test_format_stt_minutes_with_price_ignores_non_finite_or_non_positive_local_average_values() -> None:
    assert (
        format_stt_minutes_with_price(
            2.5,
            0.016,
            provider="local",
            average_inference_seconds=math.nan,
        )
        == "2.50 min (avg --)"
    )
    assert (
        format_stt_minutes_with_price(
            2.5,
            0.016,
            provider="local",
            average_inference_seconds=0.0,
        )
        == "2.50 min (avg --)"
    )
