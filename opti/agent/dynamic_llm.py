import asyncio, logging
from livekit.plugins import google, groq, openai     
from typing import Any, Dict

logger = logging.getLogger("DynamicLLM")

# map provider string → constructor
_PROVIDER_MAP = {
    "google": google.LLM,
    "gemini": google.LLM,       # alias if you store "gemini"
    "groq":   groq.LLM,
    "openai": openai.LLM,
}

_TABLE= "llm_configs"
_FALLBACK = {"provider": "google", "model": "gemini-2.0-flash", "temperature": 0.8}

class DynamicLLM:
    """
    Drop-in replacement for a LiveKit LLM plugin that reloads its provider /
    model / temperature at runtime.  Pass it to AgentSession just like a normal
    plugin.

    The only public method required by LiveKit agents is `generate()`.
    """

    def __init__(self, supabase_client, poll_seconds: int = 30):
        self._sb               = supabase_client
        self._poll_seconds     = poll_seconds
        self._current_cfg: Dict[str, Any] = {}
        self._llm              = None     # the active concrete plugin
        # Kick off background watcher
        asyncio.create_task(self._watch_loop(), name="DynamicLLM-watcher")

    # ------------- public API -------------
    async def generate(self, prompt, **kwargs):
        if self._llm is None:
            await self._refresh()               # first call
        return await self._llm.generate(prompt, **kwargs)

    # ------------- internal helpers -------------
    async def _fetch_cfg(self) -> Dict[str, Any]:
        """
        Pull the current row from Supabase.
        Returns fallback config if table/row is missing.
        """
        try:
            # Run blocking HTTP in a thread so we don't block the event loop
            response = await asyncio.to_thread(
                self._sb.table(_TABLE).select("*").eq("id", 1).single().execute
            )
            if response and response.data:
                data = response.data
                return {
                    "provider":    data.get("provider", _FALLBACK["provider"]),
                    "model":       data.get("model", _FALLBACK["model"]),
                    "temperature": data.get("temperature", _FALLBACK["temperature"]),
                }
        except Exception as exc:        # table not found, network issue, etc.
            logger.debug("Failed to fetch LLM config: %s", exc, exc_info=True)


    async def _refresh(self):
        cfg = await self._fetch_cfg()
        if cfg != self._current_cfg:
            logger.info("Switching LLM provider to %s %s (T=%s)",
                        cfg["provider"], cfg["model"], cfg["temperature"])
            ctor = _PROVIDER_MAP.get(cfg["provider"])
            if ctor is None:
                logger.error("Unknown provider %s, keeping old LLM", cfg["provider"])
                return
            self._llm          = ctor(model=cfg["model"], temperature=cfg["temperature"])
            self._current_cfg  = cfg

    async def _watch_loop(self):
        """Simple polling loop; replace with Supabase Realtime if desired."""
        while True:
            try:
                await self._refresh()
            except Exception as exc:
                logger.warning("DynamicLLM refresh failed: %s", exc)
            await asyncio.sleep(self._poll_seconds)