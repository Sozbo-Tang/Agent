import os
from dataclasses import dataclass


@dataclass
class Config:
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    timeout: int = 60
    max_steps: int = 8
    context_budget: int = 6000
    keep_recent: int = 6
    data_dir: str = ".data"


def load_config(environ=None):
    env = environ if environ is not None else os.environ
    return Config(
        api_key=env.get("LLM_API_KEY", ""),
        base_url=env.get("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
        model=env.get("LLM_MODEL", "glm-4.6"),
        timeout=int(env.get("LLM_TIMEOUT", "60")),
        max_steps=int(env.get("AGENT_MAX_STEPS", "8")),
        context_budget=int(env.get("AGENT_CONTEXT_BUDGET", "6000")),
        keep_recent=int(env.get("AGENT_KEEP_RECENT", "6")),
        data_dir=env.get("AGENT_DATA_DIR", ".data"),
    )
