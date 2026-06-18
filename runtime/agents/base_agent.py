from __future__ import annotations

from abc import ABC, abstractmethod


class BaseAgent(ABC):
    agent_name = "base_agent"

    @abstractmethod
    def run(self, request):
        raise NotImplementedError

