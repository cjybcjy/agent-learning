import pytest
from heatmap.ai.llm_client import (
    LLMClient,
    ProviderSpec,
    PROVIDERS,
    get_provider_names,
    get_provider_models,
)


def test_provider_registry_has_expected_providers():
    expected = {"deepseek", "kimi", "bailian", "claude", "openai"}
    assert set(PROVIDERS.keys()) == expected


def test_provider_names_returns_all():
    names = get_provider_names()
    assert len(names) == 5
    assert "deepseek" in names
    assert "claude" in names


def test_get_provider_models_structure():
    models = get_provider_models()
    assert len(models) == 5
    for m in models:
        assert "provider" in m
        assert "display_name" in m
        assert "default_model" in m
        assert "api_key_env" in m


def test_deepseek_spec():
    spec = PROVIDERS["deepseek"]
    assert spec.name == "deepseek"
    assert spec.display_name == "DeepSeek"
    assert spec.base_url == "https://api.deepseek.com/v1"
    assert spec.api_key_env == "DEEPSEEK_API_KEY"
    assert spec.default_model == "deepseek-chat"
    assert spec.protocol == "openai"


def test_kimi_spec():
    spec = PROVIDERS["kimi"]
    assert spec.protocol == "openai"
    assert spec.base_url == "https://api.moonshot.cn/v1"


def test_bailian_spec():
    spec = PROVIDERS["bailian"]
    assert spec.protocol == "openai"
    assert "dashscope" in spec.base_url


def test_claude_spec():
    spec = PROVIDERS["claude"]
    assert spec.protocol == "anthropic"
    assert spec.api_key_env == "ANTHROPIC_API_KEY"


def test_openai_spec():
    spec = PROVIDERS["openai"]
    assert spec.protocol == "openai"
    assert spec.base_url == "https://api.openai.com/v1"


class TestLLMClientApiKeyResolution:
    """API key resolution: explicit > env var > config_store."""

    def test_explicit_key_takes_priority(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        client = LLMClient(provider="deepseek", api_key="explicit-key")
        assert client._api_key() == "explicit-key"

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        client = LLMClient(provider="deepseek")
        assert client._api_key() == "env-key"

    def test_config_store_fallback(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        store = {"DEEPSEEK_API_KEY": "store-key"}
        client = LLMClient(provider="deepseek", config_store=store)
        # config_store.get is called; our mock dict doesn't have .get method,
        # so we need a real-like object.

    def test_raises_when_no_key_available(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        client = LLMClient(provider="deepseek")
        with pytest.raises(RuntimeError) as exc_info:
            client._api_key()
        assert "deepseek" in str(exc_info.value)
        assert "DEEPSEEK_API_KEY" in str(exc_info.value)

    def test_with_key_returns_new_client(self):
        client = LLMClient(provider="deepseek")
        new_client = client.with_key("new-key")
        assert new_client is not client
        assert new_client._api_key() == "new-key"
        # Original client unchanged
        with pytest.raises(RuntimeError):
            client._api_key()

    def test_different_providers_use_different_env_vars(self, monkeypatch):
        monkeypatch.setenv("KIMI_API_KEY", "kimi-env")
        client = LLMClient(provider="kimi")
        assert client._api_key() == "kimi-env"

    def test_default_provider_is_deepseek(self):
        client = LLMClient()
        assert client.provider.name == "deepseek"
        assert client.model == "deepseek-chat"

    def test_unknown_provider_falls_back_to_deepseek(self):
        client = LLMClient(provider="nonexistent")
        assert client.provider.name == "deepseek"


class MockConfigStore:
    """Minimal config store mock for testing."""

    def __init__(self, data: dict):
        self._data = data

    def get(self, key: str, default=None):
        env_val = __import__("os").environ.get(key)
        if env_val:
            return env_val
        return self._data.get(key, default)


def test_config_store_fallback_with_mock(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    store = MockConfigStore({"DEEPSEEK_API_KEY": "store-key"})
    client = LLMClient(provider="deepseek", config_store=store)
    assert client._api_key() == "store-key"


def test_env_overrides_config_store(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    store = MockConfigStore({"DEEPSEEK_API_KEY": "store-key"})
    client = LLMClient(provider="deepseek", config_store=store)
    assert client._api_key() == "env-key"


def test_explicit_overrides_env_and_store(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    store = MockConfigStore({"DEEPSEEK_API_KEY": "store-key"})
    client = LLMClient(provider="deepseek", api_key="explicit-key", config_store=store)
    assert client._api_key() == "explicit-key"
