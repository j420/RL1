"""SRE Incident Response Environment for OpenEnv."""

from __future__ import annotations

import uuid
from typing import Any, Optional

# Dual-import pattern: use openenv types when available, fallback otherwise
try:
    from openenv.core.env_server.types import State
    from openenv.core.env_server.environment import Environment
except ImportError:
    from pydantic import BaseModel

    class State(BaseModel):  # type: ignore[no-redef]
        episode_id: str = ""
        step: int = 0
        metadata: dict = {}

    class Environment:  # type: ignore[no-redef]
        """Minimal base class when openenv-core is not installed."""

        pass


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import IncidentAction, IncidentObservation, IncidentReward
from server.simulation import ServiceSimulation
from server.grader import IncidentGrader
from server.scenarios import SCENARIOS

AVAILABLE_COMMANDS = [
    "list_services()",
    "check_status('service_name')",
    "read_logs('service_name', lines=50)",
    "check_metrics('service_name', 'metric_name')  # cpu, memory, latency, error_rate, connections",
    "check_dependencies('service_name')",
    "restart_service('service_name')",
    "scale_service('service_name', replicas)",
    "rollback_deployment('service_name')",
    "update_config('service_name', 'key', 'value')",
    "run_healthcheck('service_name')",
    "diagnose('your diagnosis description')",
]


class IncidentEnvironment(Environment):
    """OpenEnv environment that simulates an SRE incident response workflow.

    The agent receives an incident alert and must investigate services, diagnose
    the root cause, and apply remediation -- all through text commands.
    """

    SUPPORTS_CONCURRENT_SESSIONS = True

    def __init__(self) -> None:
        self._simulation: Optional[ServiceSimulation] = None
        self._grader: Optional[IncidentGrader] = None
        self._scenario: Optional[Any] = None
        self._step_count: int = 0
        self._episode_done: bool = False
        self._state: State = State(episode_id=str(uuid.uuid4()), step=0)

    # ------------------------------------------------------------------
    # reset
    # ------------------------------------------------------------------
    def reset(
        self,
        seed: Optional[int] = None,
        episode_id: Optional[str] = None,
        **kwargs: Any,
    ) -> IncidentObservation:
        """Reset environment and present the incident alert.

        Keyword Args:
            task: Scenario key (default ``"service_crash"``).  Must be a key
                  in :pydata:`SCENARIOS`.
        """
        task_name: str = kwargs.get("task", "service_crash")
        if task_name not in SCENARIOS:
            task_name = "service_crash"

        self._scenario = SCENARIOS[task_name]
        self._simulation = ServiceSimulation(self._scenario)
        self._grader = IncidentGrader(self._scenario)
        self._step_count = 0
        self._episode_done = False
        self._state = State(
            episode_id=episode_id or str(uuid.uuid4()),
            step=0,
            metadata={"task": task_name, "difficulty": self._scenario.difficulty},
        )

        # Build the initial incident-alert text shown to the agent.
        initial_output = (
            "=== INCIDENT ALERT ===\n\n"
            f"{self._scenario.description}\n\n"
            "You are the on-call SRE. Investigate this incident, identify the "
            "root cause, and apply the appropriate fix.\n\n"
            "Available commands:\n"
        )
        for cmd in AVAILABLE_COMMANDS:
            initial_output += f"  {cmd}\n"

        return IncidentObservation(
            output=initial_output,
            incident_summary=self._scenario.description,
            services=self._simulation.get_service_names(),
            available_commands=AVAILABLE_COMMANDS,
            step_count=0,
            max_steps=self._scenario.max_steps,
            score=0.0,
            task_name=task_name,
            done=False,
            reward=0.0,
            last_action_error=None,
            metadata={"reward_breakdown": IncidentReward().model_dump()},
        )

    # ------------------------------------------------------------------
    # step
    # ------------------------------------------------------------------
    def step(self, action: IncidentAction) -> IncidentObservation:
        """Execute one SRE command and return the resulting observation."""
        if self._simulation is None or self._grader is None or self._scenario is None:
            return IncidentObservation(
                output="Environment has not been reset. Call reset() first.",
                done=True,
                reward=0.0,
                last_action_error="Environment not initialised",
            )

        if self._episode_done:
            return IncidentObservation(
                output="This episode is already finished. Call reset() to start a new one.",
                done=True,
                reward=0.0,
                score=self._grader.get_cumulative_score(),
                step_count=self._step_count,
                max_steps=self._scenario.max_steps,
                task_name=self._scenario.name,
                last_action_error="Episode already done",
            )

        self._step_count += 1
        self._state.step = self._step_count

        # Execute the command inside the simulation
        output, error = self._simulation.execute_command(action.command)

        # Score the step
        step_reward, reward_breakdown = self._grader.evaluate_step(
            self._simulation, action.command, error
        )

        # Determine whether the episode is over
        all_resolved: bool = self._simulation.is_fully_resolved()
        max_steps_reached: bool = self._step_count >= self._scenario.max_steps
        done: bool = all_resolved or max_steps_reached

        # Final scoring
        if done:
            final_score, final_breakdown = self._grader.get_final_score(
                self._step_count, self._scenario.max_steps
            )
            score = final_score
            reward_breakdown = final_breakdown
            reward: float = final_score
            self._episode_done = True
        else:
            score = self._grader.get_cumulative_score()
            reward = step_reward

        # Build the text the agent will see
        if error:
            display_output = f"ERROR: {error}\n"
            if output:
                display_output += f"\n{output}"
        else:
            display_output = output

        return IncidentObservation(
            output=display_output,
            incident_summary=self._scenario.description,
            services=self._simulation.get_service_names(),
            available_commands=AVAILABLE_COMMANDS,
            step_count=self._step_count,
            max_steps=self._scenario.max_steps,
            score=score,
            task_name=self._scenario.name,
            done=done,
            reward=reward,
            last_action_error=error,
            metadata={"reward_breakdown": reward_breakdown},
        )

    # ------------------------------------------------------------------
    # state property
    # ------------------------------------------------------------------
    @property
    def state(self) -> State:
        """Return the current environment state (episode id + step counter)."""
        return self._state
