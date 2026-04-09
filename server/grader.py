"""Grading and reward computation for the SRE Incident Response Environment.

Implements a milestone-based grading system where the agent earns score for:
- Investigating the right services (reading logs, checking status)
- Diagnosing the root cause correctly
- Applying the correct remediation
- Efficiency (fewer steps is better)

Penalties are applied for:
- Repeating the same command
- Destructive actions (restart/rollback/scale) on healthy services
- Invalid / unparseable commands
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from server.scenarios import Scenario, RootCause
from server.simulation import ServiceSimulation


class IncidentGrader:
    """Deterministic grading engine for one episode."""

    def __init__(self, scenario: Scenario) -> None:
        self._scenario = scenario
        self._achieved_milestones: Set[str] = set()
        self._prev_commands: List[str] = []
        self._total_penalty: float = 0.0
        self._total_investigation: float = 0.0
        self._total_diagnosis: float = 0.0
        self._total_remediation: float = 0.0
        self._max_penalty: float = 0.15

        # Build milestone scoring map based on difficulty
        self._milestone_scores = self._build_milestone_scores()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_step(
        self,
        simulation: ServiceSimulation,
        command: str,
        command_error: Optional[str],
    ) -> Tuple[float, Dict[str, Any]]:
        """Score a single step.  Returns ``(step_reward, breakdown_dict)``."""
        step_reward = 0.0
        step_penalty = 0.0

        # --- penalties ---------------------------------------------------
        # 1. Repeating the exact same command
        if command in self._prev_commands:
            step_penalty += 0.01

        # 2. Invalid command
        if command_error is not None:
            step_penalty += 0.005

        # 3. Destructive action on a healthy service
        destructive_cmds = {"restart_service", "rollback_deployment", "scale_service"}
        cmd_name, svc_name = self._extract_cmd_and_service(command)
        if cmd_name in destructive_cmds and svc_name:
            # Check if this service has a root cause
            root_cause_services = {rc.service for rc in self._scenario.root_causes}
            if svc_name not in root_cause_services:
                step_penalty += 0.03

        self._total_penalty = min(self._total_penalty + step_penalty, self._max_penalty)
        self._prev_commands.append(command)

        # --- milestone rewards -------------------------------------------
        current_milestones = simulation.get_achieved_milestones()
        new_milestones = current_milestones - self._achieved_milestones

        for ms in new_milestones:
            score = self._milestone_scores.get(ms, 0.0)
            step_reward += score
            # Categorise the milestone
            if "check_status" in ms or "read_logs" in ms or "check_metrics" in ms or "list_services" in ms:
                self._total_investigation += score
            elif "diagnose" in ms:
                self._total_diagnosis += score
            else:
                self._total_remediation += score

        self._achieved_milestones = current_milestones.copy()

        # --- check if root causes were just resolved --------------------
        # Award remediation score for fixing root causes
        for rc in self._scenario.root_causes:
            rc_key = self._rc_milestone_key(rc)
            if rc_key not in self._achieved_milestones and simulation.is_fully_resolved():
                pass  # will be checked via investigation_milestones

        # Check for remediation milestones from fix actions
        for rc in self._scenario.root_causes:
            fix_key = self._get_fix_milestone_key(rc)
            if fix_key and fix_key in new_milestones:
                pass  # already counted above

        net_step_reward = max(0.0, step_reward - step_penalty)

        breakdown = {
            "investigation_score": round(self._total_investigation, 4),
            "diagnosis_score": round(self._total_diagnosis, 4),
            "remediation_score": round(self._total_remediation, 4),
            "efficiency_bonus": 0.0,
            "penalty": round(-self._total_penalty, 4),
            "total": round(self.get_cumulative_score(), 4),
        }

        return round(net_step_reward, 4), breakdown

    def get_final_score(
        self, total_steps: int, max_steps: int
    ) -> Tuple[float, Dict[str, Any]]:
        """Compute the final episode score with efficiency bonus.

        Returns ``(score, breakdown_dict)`` where score is in [0.001, 0.999].
        """
        # Efficiency bonus: solve faster = better
        if total_steps < max_steps and self._total_remediation > 0:
            steps_saved_ratio = (max_steps - total_steps) / max_steps
            efficiency_bonus = min(0.10, steps_saved_ratio * 0.15)
        else:
            efficiency_bonus = 0.0

        raw_score = (
            self._total_investigation
            + self._total_diagnosis
            + self._total_remediation
            + efficiency_bonus
            - self._total_penalty
        )

        # Clamp to [0.001, 0.999]
        final_score = max(0.001, min(0.999, raw_score))

        breakdown = {
            "investigation_score": round(self._total_investigation, 4),
            "diagnosis_score": round(self._total_diagnosis, 4),
            "remediation_score": round(self._total_remediation, 4),
            "efficiency_bonus": round(efficiency_bonus, 4),
            "penalty": round(-self._total_penalty, 4),
            "total": round(final_score, 4),
        }

        return round(final_score, 4), breakdown

    def get_cumulative_score(self) -> float:
        """Current cumulative score (without efficiency bonus)."""
        raw = (
            self._total_investigation
            + self._total_diagnosis
            + self._total_remediation
            - self._total_penalty
        )
        return round(max(0.0, min(1.0, raw)), 4)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_milestone_scores(self) -> Dict[str, float]:
        """Build a map from milestone string -> score value.

        Milestone strings match what ServiceSimulation puts in
        ``_achieved_milestones`` (see ``_update_milestones``).
        """
        milestones = self._scenario.investigation_milestones
        difficulty = self._scenario.difficulty
        scores: Dict[str, float] = {}

        if difficulty == "easy":
            # Easy: total = 1.0
            # investigation: ~0.30, remediation: ~0.40, rest: efficiency
            score_map = {
                "list_services": 0.05,
                "check_status": 0.10,
                "read_logs": 0.10,
                "check_metrics": 0.05,
                "check_dependencies": 0.05,
                "rollback": 0.40,
                "update_config": 0.35,
                "restart": 0.20,
                "diagnose": 0.15,
            }
        elif difficulty == "medium":
            score_map = {
                "list_services": 0.05,
                "check_status": 0.08,
                "read_logs": 0.08,
                "check_metrics": 0.04,
                "check_dependencies": 0.05,
                "rollback": 0.25,
                "update_config": 0.25,
                "restart": 0.10,
                "diagnose": 0.10,
            }
        else:  # hard
            score_map = {
                "list_services": 0.03,
                "check_status": 0.05,
                "read_logs": 0.05,
                "check_metrics": 0.03,
                "check_dependencies": 0.02,
                "rollback": 0.15,
                "update_config": 0.12,
                "restart": 0.08,
                "diagnose": 0.07,
            }

        for ms_key in milestones:
            matched = False
            for prefix, score in score_map.items():
                if ms_key.startswith(prefix) or prefix in ms_key:
                    scores[ms_key] = score
                    matched = True
                    break
            if not matched:
                scores[ms_key] = 0.02  # default small score

        return scores

    def _extract_cmd_and_service(self, command: str) -> Tuple[str, Optional[str]]:
        """Quick extraction of command name and first service argument."""
        import re
        m = re.match(r"^(\w+)\s*\(", command)
        if not m:
            return "", None
        cmd_name = m.group(1)
        # Extract first string argument
        arg_match = re.search(r"['\"]([^'\"]+)['\"]", command)
        svc_name = arg_match.group(1) if arg_match else None
        return cmd_name, svc_name

    def _rc_milestone_key(self, rc: RootCause) -> str:
        return f"fixed_{rc.service}"

    def _get_fix_milestone_key(self, rc: RootCause) -> Optional[str]:
        if rc.fix_type == "rollback":
            return f"rollback_{rc.service}"
        elif rc.fix_type == "update_config":
            return f"update_config_{rc.service}"
        elif rc.fix_type == "restart":
            return f"restart_{rc.service}"
        return None
