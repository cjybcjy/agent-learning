from __future__ import annotations

from sentinel.mgfs.factor_plugin import BaseFactorPlugin


class FactorPluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, BaseFactorPlugin] = {}

    def register(self, plugin: BaseFactorPlugin) -> None:
        self._plugins[plugin.factor_key] = plugin

    def list_by_keys(self, keys: list[str]) -> list[BaseFactorPlugin]:
        resolved: list[BaseFactorPlugin] = []
        for key in keys:
            if key not in self._plugins:
                raise KeyError(f"factor not registered: {key}")
            resolved.append(self._plugins[key])
        return resolved

    def list_all(self) -> list[BaseFactorPlugin]:
        return list(self._plugins.values())
