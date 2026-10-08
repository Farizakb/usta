from pydantic import BaseModel, ConfigDict


class Frozen(BaseModel):
    """Immutable domain value."""

    model_config = ConfigDict(frozen=True)
