"""Telegram-specific gateway filtering for noisy status/error output."""

from gateway.config import Platform
from gateway.run import (
    _prepare_gateway_status_message,
    _sanitize_gateway_final_response,
)


def test_telegram_status_suppresses_auxiliary_and_retry_noise():
    """Auxiliary failures and retry backoff chatter should not hit Telegram."""
    noisy_messages = [
        "⚠ Auxiliary title generation failed: HTTP 400: Operation contains cybersecurity risk",
        "⚠ Compression summary failed: upstream error. Inserted a fallback context marker.",
        "🗜️ Compacting context — summarizing earlier conversation so I can continue...",
        "ℹ Configured compression model 'small-model' failed (timeout). Recovered using main model — check auxiliary.compression.model in config.yaml.",
        "⏳ Retrying in 4.2s (attempt 1/3)...",
        "⏱️ Rate limited. Waiting 30.0s (attempt 2/3)...",
        "⚠️ Max retries (3) exhausted — trying fallback...",
    ]

    for message in noisy_messages:
        assert _prepare_gateway_status_message(Platform.TELEGRAM, "warn", message) is None


def test_status_noise_filtered_on_all_platforms():
    """Hermes has no OpenClaw error-filter, so the quieting/sanitizing policy
    now applies to every surface (Matrix/WhatsApp/Discord), not Telegram only."""
    noisy = "⏳ Retrying in 4.2s (attempt 1/3)..."
    for platform in (Platform.DISCORD, "matrix", "local"):
        assert _prepare_gateway_status_message(platform, "lifecycle", noisy) is None


def test_non_telegram_final_response_sanitizes_provider_errors():
    """A raw provider error must be rewritten on non-Telegram platforms too."""
    raw = (
        "API call failed after 3 retries: HTTP 400: blocked under the provider "
        "cybersecurity risk policy. request_id=req_xyz"
    )
    for platform in ("matrix", Platform.DISCORD):
        sanitized = _sanitize_gateway_final_response(platform, raw)
        assert "provider rejected" in sanitized.lower()
        assert "cybersecurity risk" not in sanitized.lower()
        assert "HTTP 400" not in sanitized
        assert "req_xyz" not in sanitized


def test_final_response_strips_raw_tool_call_json():
    """Leaked raw tool-call JSON (model emitted it as text) is replaced."""
    leaked = '{"name": "cron", "parameters": {"schedule": "* * * * *"}}'
    out = _sanitize_gateway_final_response("matrix", leaked)
    assert out != leaked
    assert "parameters" not in out
    assert "problem completing that action" in out.lower()
    # A legitimate markdown-fenced JSON answer must NOT be clobbered.
    legit = 'Here is the config:\n```json\n{"name": "value"}\n```'
    assert _sanitize_gateway_final_response("matrix", legit) == legit


def test_telegram_status_sanitizes_raw_provider_security_errors():
    """Provider policy/security bodies should be replaced before chat delivery."""
    raw = (
        "❌ API failed after 3 retries — HTTP 400: request blocked because "
        "Operation contains cybersecurity risk. request_id=req_123"
    )

    sanitized = _prepare_gateway_status_message(Platform.TELEGRAM, "lifecycle", raw)

    assert sanitized is not None
    assert "provider rejected" in sanitized.lower()
    assert "cybersecurity risk" not in sanitized.lower()
    assert "HTTP 400" not in sanitized
    assert "req_123" not in sanitized


def test_telegram_final_response_sanitizes_raw_provider_errors():
    """Final Telegram replies should not expose raw provider/security details."""
    raw = (
        "API call failed after 3 retries: HTTP 400: This request was blocked "
        "under the provider cybersecurity risk policy. request_id=req_abc"
    )

    sanitized = _sanitize_gateway_final_response(Platform.TELEGRAM, raw)

    assert "provider rejected" in sanitized.lower()
    assert "cybersecurity risk" not in sanitized.lower()
    assert "HTTP 400" not in sanitized
    assert "req_abc" not in sanitized


def test_telegram_final_response_redacts_auth_secrets():
    """Authentication errors should be useful without leaking key material."""
    raw = (
        "⚠️ Provider authentication failed: Incorrect API key provided: "
        "sk-live_abcdefghijklmnopqrstuvwxyz1234567890"
    )

    sanitized = _sanitize_gateway_final_response(Platform.TELEGRAM, raw)

    assert "authentication failed" in sanitized.lower()
    assert "check the configured credentials" in sanitized.lower()
    assert "sk-live" not in sanitized


def test_telegram_final_response_keeps_normal_answers():
    """Normal assistant content should not be rewritten."""
    answer = "Here is the clean summary you asked for."

    assert _sanitize_gateway_final_response(Platform.TELEGRAM, answer) == answer
