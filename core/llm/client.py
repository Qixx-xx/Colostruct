"""Small Ollama HTTP client using only the Python standard library.

No clinical data is sent to a cloud provider. The default endpoint is loopback.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMError(RuntimeError):
    """Raised when the local model cannot return a usable response."""


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:8b"
    timeout_seconds: int = 180
    temperature: float = 0.0
    keep_alive: str = "10m"
    think: bool = False

    @classmethod
    def from_env(cls) -> "OllamaConfig":
        think = os.getenv("COLOSTRUCT_OLLAMA_THINK", "").strip().lower() in {
            "1", "true", "yes", "on"
        }
        return cls(
            base_url=os.getenv("COLOSTRUCT_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            model=os.getenv("COLOSTRUCT_LLM_MODEL", "qwen3:8b"),
            timeout_seconds=int(os.getenv("COLOSTRUCT_LLM_TIMEOUT", "180")),
            temperature=float(os.getenv("COLOSTRUCT_LLM_TEMPERATURE", "0")),
            keep_alive=os.getenv("COLOSTRUCT_OLLAMA_KEEP_ALIVE", "10m"),
            think=think,
        )


class OllamaClient:
    """Calls Ollama's local /api/chat endpoint."""

    def __init__(self, config: OllamaConfig | None = None):
        self.config = config or OllamaConfig.from_env()

    def generate_json(self, *, system: str, user: str) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "think": self.config.think,
            "options": {"temperature": self.config.temperature},
            "keep_alive": self.config.keep_alive,
        }
        request = Request(
            f"{self.config.base_url}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # Do not copy the server body: it may contain prompt/model output.
            _ = exc.read()  # consume the body; never expose it
            raise LLMError("Ollama HTTP error: status %s" % exc.code) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise LLMError(
                f"Cannot reach Ollama at {self.config.base_url}. "
                "Check that Ollama is running and the model is installed."
            ) from exc
        except json.JSONDecodeError as exc:
            raise LLMError("Ollama returned an invalid HTTP JSON response.") from exc

        message = response_data.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMError("Ollama returned an empty message.")
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError("Model response was not valid JSON despite JSON mode.") from exc
        if not isinstance(result, dict):
            raise LLMError("Model JSON root must be an object.")
        return result
