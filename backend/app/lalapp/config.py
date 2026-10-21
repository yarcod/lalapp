from pydantic_settings import BaseSettings, SettingsConfigDict


class LalappSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LALAPP_", extra="ignore")

    # Shadow mode: record learner ability estimates without changing user-facing behaviour.
    LEARNER_MODEL_ENABLED: bool = True
    # Characters replace the single upstream tutor in text chat and voice conversations.
    PERSONAS_ENABLED: bool = True


lalapp_settings = LalappSettings()
