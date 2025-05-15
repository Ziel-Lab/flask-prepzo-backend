   
import asyncio, random, logging
from livekit.plugins.google import LLM as _GoogleLLM

_SEM = asyncio.Semaphore(int(os.getenv("GEMINI_MAX_CONCURRENCY", 3)))
_log = logging.getLogger("google-llm-wrapper")

class GoogleLLM(_GoogleLLM):
    async def safe_generate(self, *args, **kwargs):
        """Run the normal generate/stream call with bounded concurrency
        and exponential-back-off retries on 5xx errors."""
        backoff = 1.0
        attempts = 0
        while True:
           attempts += 1
           try:
             async with _SEM:
                return await super().chat(*args, **kwargs)
           except Exception as e:
                if "503" not in str(e) or attempts >= 5:
                       raise
                jitter = random.uniform(0, 0.3)
                _log.warning(
                       "Gemini 503, retrying (%s/5) in %.1fs", attempts, backoff + jitter
                )
                await asyncio.sleep(backoff + jitter)
                backoff *= 2           # 1,2,4,8 …