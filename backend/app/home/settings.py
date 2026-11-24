from pydantic_settings import BaseSettings, SettingsConfigDict


class HomeSettings(BaseSettings):
    """Home-deployment settings, read from the same environment as upstream settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Reasoning effort for the local voice reply; empty means do not send.
    VOICE_REASONING_EFFORT: str = "low"
    # Thinking budget for stock game generation on the full model; empty or 0 means do not send.
    GAME_REASONING_EFFORT: str = "medium"
    GAME_MAX_TOKENS: int = 32768
    # Serve games only from the pre-generated stock (with the local ollama model).
    HOME_GAME_STOCK: bool = False


home_settings = HomeSettings()
