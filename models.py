from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

# Use try/except for dual-import compatibility (Docker vs repo)
try:
    from openenv.core.env_server.types import Action, Observation, State
except ImportError:
    # Fallback for standalone usage
    class Action(BaseModel):
        metadata: Dict[str, Any] = Field(default_factory=dict)

    class Observation(BaseModel):
        done: bool = False
        reward: Union[bool, int, float, None] = None
        metadata: Dict[str, Any] = Field(default_factory=dict)

    class State(BaseModel):
        episode_id: str = ""
        step: int = 0
        metadata: Dict[str, Any] = Field(default_factory=dict)


class IncidentAction(Action):
    """An action taken by the SRE agent during incident response."""

    command: str = Field(
        ..., description="Command to execute, e.g. check_status('api-gateway')"
    )


class IncidentObservation(Observation):
    """Observation returned to the agent after each action."""

    output: str = Field(default="", description="Text output from last command")
    incident_summary: str = Field(default="", description="Current incident alert")
    services: List[str] = Field(default_factory=list)
    available_commands: List[str] = Field(default_factory=list)
    step_count: int = Field(default=0)
    max_steps: int = Field(default=15)
    score: float = Field(default=0.0, description="Cumulative score 0.0-1.0")
    task_name: str = Field(default="")
    last_action_error: Optional[str] = Field(default=None)


class IncidentReward(BaseModel):
    """Structured reward breakdown for transparency."""

    investigation_score: float = 0.0
    diagnosis_score: float = 0.0
    remediation_score: float = 0.0
    efficiency_bonus: float = 0.0
    penalty: float = 0.0
    total: float = 0.0
