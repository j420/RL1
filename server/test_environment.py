"""Tests for the SRE Incident Response Environment."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import IncidentAction
from server.environment import IncidentEnvironment


# ======================================================================
# Reset
# ======================================================================

class TestReset:
    def test_reset_default_task(self):
        env = IncidentEnvironment()
        obs = env.reset()
        assert obs.task_name == "service_crash"
        assert obs.done is False
        assert obs.step_count == 0
        assert obs.score == 0.0
        assert len(obs.services) > 0
        assert len(obs.available_commands) > 0

    def test_reset_each_task(self):
        env = IncidentEnvironment()
        for task in ["service_crash", "cascading_failure", "multi_factor_degradation"]:
            obs = env.reset(task=task)
            assert obs.task_name == task
            assert obs.done is False
            assert "ALERT" in obs.output or "INCIDENT" in obs.output

    def test_reset_invalid_task_defaults(self):
        env = IncidentEnvironment()
        obs = env.reset(task="nonexistent_task")
        assert obs.task_name == "service_crash"

    def test_reset_clears_state(self):
        env = IncidentEnvironment()
        obs = env.reset(task="service_crash")
        env.step(IncidentAction(command="list_services()"))
        obs2 = env.reset(task="service_crash")
        assert obs2.step_count == 0
        assert obs2.done is False


# ======================================================================
# Step — basic commands
# ======================================================================

class TestStepCommands:
    def test_list_services(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        obs = env.step(IncidentAction(command="list_services()"))
        assert "api-gateway" in obs.output
        assert "user-service" in obs.output
        assert obs.done is False
        assert obs.last_action_error is None

    def test_check_status(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        obs = env.step(IncidentAction(command="check_status('user-service')"))
        assert "DOWN" in obs.output or "down" in obs.output.lower()
        assert obs.last_action_error is None

    def test_read_logs(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        obs = env.step(IncidentAction(command="read_logs('user-service')"))
        assert obs.last_action_error is None
        output_lower = obs.output.lower()
        assert "outofmemory" in output_lower or "oom" in output_lower or "memory" in output_lower

    def test_check_metrics(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        obs = env.step(IncidentAction(command="check_metrics('api-gateway', 'cpu')"))
        assert "cpu" in obs.output.lower() or "CPU" in obs.output
        assert obs.last_action_error is None

    def test_check_dependencies(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        obs = env.step(IncidentAction(command="check_dependencies('api-gateway')"))
        assert "api-gateway" in obs.output
        assert obs.last_action_error is None

    def test_run_healthcheck(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        obs = env.step(IncidentAction(command="run_healthcheck('user-service')"))
        assert "FAIL" in obs.output or "PASS" in obs.output
        assert obs.last_action_error is None

    def test_diagnose(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        obs = env.step(IncidentAction(command="diagnose('OOM crash in user-service')"))
        assert obs.last_action_error is None

    def test_invalid_command(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        obs = env.step(IncidentAction(command="fly_to_moon()"))
        assert obs.last_action_error is not None

    def test_malformed_command(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        obs = env.step(IncidentAction(command="this is not a command"))
        assert obs.last_action_error is not None

    def test_unknown_service(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        obs = env.step(IncidentAction(command="check_status('nonexistent')"))
        assert obs.last_action_error is not None

    def test_invalid_metric(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        obs = env.step(IncidentAction(command="check_metrics('api-gateway', 'bananas')"))
        assert obs.last_action_error is not None


# ======================================================================
# Step — termination
# ======================================================================

class TestTermination:
    def test_max_steps_terminates(self):
        env = IncidentEnvironment()
        obs = env.reset(task="service_crash")
        for _ in range(20):
            obs = env.step(IncidentAction(command="list_services()"))
            if obs.done:
                break
        assert obs.done is True

    def test_step_after_done(self):
        env = IncidentEnvironment()
        obs = env.reset(task="service_crash")
        for _ in range(20):
            obs = env.step(IncidentAction(command="list_services()"))
            if obs.done:
                break
        obs2 = env.step(IncidentAction(command="list_services()"))
        assert obs2.done is True
        assert obs2.last_action_error is not None


# ======================================================================
# Easy task: service_crash
# ======================================================================

class TestEasyTask:
    def test_solve_service_crash(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        env.step(IncidentAction(command="list_services()"))
        env.step(IncidentAction(command="check_status('user-service')"))
        env.step(IncidentAction(command="read_logs('user-service')"))
        obs = env.step(IncidentAction(command="rollback_deployment('user-service')"))
        assert obs.score > 0.4, f"Expected score > 0.4, got {obs.score}"

    def test_deterministic_grading(self):
        scores = []
        for _ in range(2):
            env = IncidentEnvironment()
            env.reset(task="service_crash")
            env.step(IncidentAction(command="check_status('user-service')"))
            env.step(IncidentAction(command="read_logs('user-service')"))
            obs = env.step(IncidentAction(command="rollback_deployment('user-service')"))
            scores.append(obs.score)
        assert scores[0] == scores[1], f"Scores differ: {scores}"


# ======================================================================
# Medium task: cascading_failure
# ======================================================================

class TestMediumTask:
    def test_solve_cascading_failure(self):
        env = IncidentEnvironment()
        env.reset(task="cascading_failure")
        env.step(IncidentAction(command="list_services()"))
        env.step(IncidentAction(command="check_status('cache-service')"))
        env.step(IncidentAction(command="read_logs('cache-service')"))
        obs = env.step(IncidentAction(command="update_config('cache-service', 'maxmemory', '512mb')"))
        assert obs.score > 0.3, f"Expected score > 0.3, got {obs.score}"


# ======================================================================
# Hard task: multi_factor_degradation
# ======================================================================

class TestHardTask:
    def test_solve_multi_factor(self):
        env = IncidentEnvironment()
        env.reset(task="multi_factor_degradation")
        # Fix api-gateway verbose logging
        env.step(IncidentAction(command="check_status('api-gateway')"))
        env.step(IncidentAction(command="read_logs('api-gateway')"))
        env.step(IncidentAction(command="update_config('api-gateway', 'verbose_logging', 'false')"))
        # Fix auth-service SSL cert
        env.step(IncidentAction(command="check_status('auth-service')"))
        env.step(IncidentAction(command="read_logs('auth-service')"))
        env.step(IncidentAction(command="update_config('auth-service', 'ssl_cert_path', '/certs/renewed/server.pem')"))
        # Fix payment-service bad deploy
        env.step(IncidentAction(command="check_status('payment-service')"))
        env.step(IncidentAction(command="read_logs('payment-service')"))
        obs = env.step(IncidentAction(command="rollback_deployment('payment-service')"))
        assert obs.score > 0.4, f"Expected score > 0.4, got {obs.score}"


# ======================================================================
# Reward function properties
# ======================================================================

class TestRewardFunction:
    def test_rewards_between_0_and_1(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        for _ in range(15):
            obs = env.step(IncidentAction(command="list_services()"))
            assert 0.0 <= obs.score <= 1.0
            if obs.done:
                break

    def test_partial_progress(self):
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        obs1 = env.step(IncidentAction(command="check_status('user-service')"))
        s1 = obs1.score
        obs2 = env.step(IncidentAction(command="rollback_deployment('user-service')"))
        s2 = obs2.score
        assert s2 > s1, f"Score should increase: {s1} -> {s2}"

    def test_no_crash_on_healthy_restart(self):
        """Restarting a healthy service should not crash."""
        env = IncidentEnvironment()
        env.reset(task="service_crash")
        obs = env.step(IncidentAction(command="restart_service('database')"))
        assert obs.last_action_error is None  # Not an error, just a penalty
