from pydantic_settings import BaseSettings, SettingsConfigDict


class HomeSettings(BaseSettings):
    """Home-deployment settings, read from the same environment as upstream settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Reasoning effort for the local voice reply; empty means do not send.
    VOICE_REASONING_EFFORT: str = "low"


home_settings = HomeSettings()
