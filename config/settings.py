"""Application settings and configuration management."""

import os
from dataclasses import dataclass, field
from typing import Optional
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass
class AzureConfig:
    """Azure AI configuration."""
    project_endpoint: str = field(default_factory=lambda: os.environ.get("AZURE_AI_PROJECT_ENDPOINT", ""))
    agent1_id: str = field(default_factory=lambda: os.environ.get("AZURE_AI_AGENT_ID", ""))
    # Future: Add more agent IDs as needed
    # agent2_id: str = field(default_factory=lambda: os.environ.get("AZURE_AI_AGENT2_ID", ""))


@dataclass
class LLMConfig:
    """LLM configuration for LangChain agents."""
    provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "azure_openai"))
    # Azure OpenAI settings
    azure_openai_endpoint: str = field(default_factory=lambda: os.environ.get("AZURE_OPENAI_ENDPOINT", ""))
    azure_openai_api_key: str = field(default_factory=lambda: os.environ.get("AZURE_OPENAI_API_KEY", ""))
    azure_openai_deployment: str = field(default_factory=lambda: os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"))
    azure_openai_api_version: str = field(default_factory=lambda: os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"))
    # OpenAI settings (alternative)
    openai_api_key: str = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.environ.get("OPENAI_MODEL", "gpt-4o"))
    # Common settings
    temperature: float = field(default_factory=lambda: float(os.environ.get("LLM_TEMPERATURE", "0.1")))
    max_tokens: int = field(default_factory=lambda: int(os.environ.get("LLM_MAX_TOKENS", "4096")))


@dataclass
class Settings:
    """Main application settings."""
    azure: AzureConfig = field(default_factory=AzureConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    debug: bool = field(default_factory=lambda: os.environ.get("DEBUG", "false").lower() == "true")

    def validate(self) -> list[str]:
        """Validate settings and return list of errors."""
        errors = []

        if not self.azure.project_endpoint:
            errors.append("AZURE_AI_PROJECT_ENDPOINT is not set")
        if not self.azure.agent1_id:
            errors.append("AZURE_AI_AGENT_ID is not set")

        # Validate LLM config based on provider
        if self.llm.provider == "azure_openai":
            if not self.llm.azure_openai_endpoint:
                errors.append("AZURE_OPENAI_ENDPOINT is not set")
            if not self.llm.azure_openai_api_key:
                errors.append("AZURE_OPENAI_API_KEY is not set")
        elif self.llm.provider == "openai":
            if not self.llm.openai_api_key:
                errors.append("OPENAI_API_KEY is not set")

        return errors


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
