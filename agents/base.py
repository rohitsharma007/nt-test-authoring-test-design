"""Base agent class for the multi-agent system."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class AgentStatus(Enum):
    """Agent execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class AgentResult:
    """Result from agent execution."""
    status: AgentStatus
    data: Any = None
    raw_output: str = ""
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == AgentStatus.COMPLETED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "data": self.data,
            "raw_output": self.raw_output,
            "error": self.error,
            "metadata": self.metadata,
        }


class BaseAgent(ABC):
    """Abstract base class for all agents."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._status = AgentStatus.PENDING

    @property
    def status(self) -> AgentStatus:
        return self._status

    @abstractmethod
    async def execute(self, input_data: Any, **kwargs) -> AgentResult:
        """Execute the agent's main task."""
        pass

    def validate_input(self, input_data: Any) -> List[str]:
        """Validate input data. Returns list of validation errors."""
        return []

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, status={self.status.value})"
