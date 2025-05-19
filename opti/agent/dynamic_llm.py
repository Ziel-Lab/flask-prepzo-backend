import asyncio, logging
from livekit.plugins import google, groq, openai
from typing import Any, Dict
from ..utils.aws_secrets import load_aws_secrets
import os

logger = logging.getLogger("DynamicLLM")

class DynamicLLM:
    """
    Drop-in replacement for a LiveKit LLM plugin that reloads its provider /
    model / temperature at runtime. Pass it to AgentSession just like a normal
    plugin.

    The only public method required by LiveKit agents is `generate()`.
    """

    def __init__(self, supabase_client):
        self._sb = supabase_client
        self._llm = None

    async def generate(self, prompt, **kwargs):
        if self._llm is None:
            await self._refresh()  # first call
        return await self._llm.generate(prompt, **kwargs)

    async def _refresh(self):
        # Load secrets from AWS
        load_aws_secrets('dev-prepzo', region_name='us-east-1')

        # Fetch provider and model from environment variables
        provider = os.getenv('LLM_PROVIDER')
        model = os.getenv('LLM_MODEL')
        temperature = float(os.getenv('LLM_TEMPERATURE', 0.8))

        # Select the appropriate LLM based on the provider
        if provider == "google":
            self._llm = google.LLM(model=model, temperature=temperature)
        elif provider == "groq":
            self._llm = groq.LLM(model=model)
        elif provider == "openai":
            self._llm = openai.LLM(model=model)
        else:
            logger.error("Unknown provider %s, keeping old LLM", provider)
            return

        logger.info("LLM provider set to %s with model %s", provider, model)
