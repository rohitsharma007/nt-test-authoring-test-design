"""Azure client utilities."""

from functools import lru_cache
from typing import Optional

from azure.identity import (
    AzureCliCredential,
    InteractiveBrowserCredential,
    ChainedTokenCredential,
    DefaultAzureCredential,
)
from azure.ai.agents import AgentsClient

from config.settings import get_settings


@lru_cache()
def get_azure_credential():
    """Get Azure credential with fallback chain."""
    try:
        cli_cred = AzureCliCredential()
        credential = ChainedTokenCredential(
            cli_cred,
            InteractiveBrowserCredential()
        )
    except Exception:
        try:
            credential = DefaultAzureCredential()
        except Exception:
            credential = InteractiveBrowserCredential()
    return credential


def create_agents_client(endpoint: Optional[str] = None) -> AgentsClient:
    """Create Azure AI Agents client."""
    settings = get_settings()
    endpoint = endpoint or settings.azure.project_endpoint

    if not endpoint:
        raise ValueError("Azure AI Project endpoint is not configured")

    credential = get_azure_credential()
    return AgentsClient(endpoint=endpoint, credential=credential)


def collect_assistant_text(message) -> str:
    """Safely collect the assistant text from message content parts."""
    parts = []
    try:
        for c in (message.content or []):
            if getattr(c, "text", None) and getattr(c.text, "value", None):
                parts.append(c.text.value)
    except Exception:
        pass
    return "\n".join(parts).strip()
