from pydantic_settings import BaseSettings, SettingsConfigDict


class LalappSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LALAPP_", extra="ignore")

    # Shadow mode: record learner ability estimates without changing user-facing behaviour.
    LEARNER_MODEL_ENABLED: bool = True
    # Characters replace the single upstream tutor in text chat and voice conversations.
    PERSONAS_ENABLED: bool = True
    # Adaptive "next up" lessons and level-up suggestions driven by the learner model.
    ADAPTIVE_ENABLED: bool = True
    # Role-play scenes with NPCs and missions checked by an LLM judge.
    SCENARIOS_ENABLED: bool = True
    # Self-set weekly rhythm, target-language turn counts and informational milestones.
    RHYTHM_ENABLED: bool = True


lalapp_settings = LalappSettings()
