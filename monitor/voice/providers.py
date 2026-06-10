"""Provider protocols and registry for the unified voice domain."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from .capabilities import normalize_provider_id


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str
    capabilities: list[str]
    configured: bool = False
    fields: list[str] = field(default_factory=list)
    modes: list[str] = field(default_factory=list)
    safety: dict[str, Any] = field(default_factory=dict)
    config_reason: str | None = None
    sort_order: int = 50


@runtime_checkable
class SpeechSynthesisProvider(Protocol):
    provider_id: str

    def info(self) -> ProviderInfo:
        raise NotImplementedError

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        raise NotImplementedError

    def synthesize(self, request: Any, cfg: Mapping[str, Any]) -> Any:
        raise NotImplementedError


@runtime_checkable
class TranscriptionProvider(Protocol):
    provider_id: str

    def info(self) -> ProviderInfo:
        raise NotImplementedError

    def is_configured(self, cfg: Mapping[str, Any]) -> bool:
        raise NotImplementedError

    def transcribe(self, request: Any, cfg: Mapping[str, Any]) -> Any:
        raise NotImplementedError


class VoiceProviderRegistry:
    def __init__(self):
        self._providers: dict[str, Any] = {}

    def register(self, provider: Any) -> Any:
        provider_id = normalize_provider_id(getattr(provider, "provider_id", ""))
        if not provider_id:
            raise ValueError("voice provider must define provider_id")
        if provider_id in self._providers:
            raise ValueError(f"voice provider already registered: {provider_id}")
        self._providers[provider_id] = provider
        return provider

    def get(self, provider_id: str | None) -> Any | None:
        return self._providers.get(normalize_provider_id(provider_id))

    def require(self, provider_id: str | None) -> Any:
        normalized = normalize_provider_id(provider_id)
        provider = self._providers.get(normalized)
        if provider is None:
            raise KeyError(f"voice provider is not registered: {normalized}")
        return provider

    def providers(self) -> list[Any]:
        return sorted(self._providers.values(), key=self._sort_key)

    def providers_for_capability(self, capability: str) -> list[Any]:
        return [
            provider
            for provider in self.providers()
            if capability in set(provider.info().capabilities)
        ]

    def provider_ids(self) -> list[str]:
        return [provider.provider_id for provider in self.providers()]

    @staticmethod
    def _sort_key(provider: Any) -> tuple[int, str]:
        info = provider.info()
        return (info.sort_order, normalize_provider_id(info.id))
