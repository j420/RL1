#!/usr/bin/env python3
"""Baseline inference script for the SRE Incident Response Environment.

Uses an LLM (via OpenAI-compatible API) to investigate and resolve
production incidents across three difficulty levels.

Environment variables:
    API_BASE_URL  – LLM endpoint (default: https://api.openai.com/v1)
    MODEL_NAME    – Model identifier (default: gpt-4.1-mini)
    HF_TOKEN      – Hugging Face / API token (**required**)
"""

from __future__ import annotations

import os
import sys
import traceback

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openai import OpenAI

from models import IncidentAction
from server.environment import IncidentEnvironment

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_BASE_URL = os.getenv("API_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4.1-mini")
HF_TOKEN = os.getenv("HF_TOKEN")

if HF_TOKEN is None:
    raise ValueError(
        "HF_TOKEN environment variable is required. "
        "Set it to your Hugging Face API token or OpenAI API key."
    )

client = OpenAI(base_url=API_BASE_URL, api_key=HF_TOKEN)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are an expert Site Reliability Engineer (SRE) on-call for a production \
microservice platform. You have just been paged about an active incident. \
Your job is to systematically investigate, diagnose the root cause, and \
apply the correct fix.

## Available Commands

You can run exactly ONE command per turn. Respond with the command only — \
no explanations, no markdown, no extra text.

Investigation commands:
  list_services()                          – Overview of all services with status and metrics
  check_status('service_name')             – Detailed status of a single service
  read_logs('service_name')                – Recent log entries (add lines=N for fewer)
  read_logs('service_name', lines=20)      – Read last 20 log lines
  check_metrics('service_name', 'metric')  – Time-series metric data
                                             Metrics: cpu, memory, latency, error_rate, connections
  check_dependencies('service_name')       – Dependency tree with health status

Remediation commands:
  restart_service('service_name')                     – Restart a service
  scale_service('service_name', N)                    – Scale to N replicas
  rollback_deployment('service_name')                 – Rollback to previous deployment version
  update_config('service_name', 'key', 'value')       – Update a configuration parameter
  run_healthcheck('service_name')                     – Run comprehensive health check

Diagnosis:
  diagnose('your diagnosis here')          – Record your root-cause diagnosis

## Investigation Strategy

1. Start with list_services() to see the big picture.
2. For each DEGRADED or DOWN service, run check_status() to get details.
3. Read logs of suspicious services — logs contain the most important clues.
4. Check metrics if you need to see trends (memory leaks, CPU spikes, etc.).
5. Use check_dependencies() to understand blast radius.
6. Once you understand the root cause, apply the fix:
   - Bad deployment? → rollback_deployment('service')
   - Misconfigured setting? → update_config('service', 'key', 'correct_value')
   - Service crashed? → restart_service('service') (if no deeper issue)
7. After fixing, optionally run run_healthcheck() to verify.

## Important Rules

- Respond with EXACTLY ONE command per turn. Nothing else.
- Do NOT repeat the same command — you will be penalised.
- Do NOT restart or rollback healthy services — you will be penalised.
- Focus on the services that are DOWN or DEGRADED first.
- Read logs carefully — they contain timestamps and error messages that \
  point to the root cause.
- There may be multiple independent root causes (especially in harder tasks).
"""

TASKS = ["service_crash", "cascading_failure", "multi_factor_degradation"]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_task(task_name: str) -> None:
    """Run a single task and print [START]/[STEP]/[END] output."""
    env = IncidentEnvironment()
    obs = env.reset(task=task_name)

    print(f"[START] task={task_name} env=incident_response model={MODEL_NAME}")

    rewards: list[float] = []
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": obs.output},
    ]

    try:
        for step_num in range(1, obs.max_steps + 1):
            # Ask the LLM for an action
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                temperature=0.1,
                max_tokens=200,
            )
            action_str = response.choices[0].message.content or ""
            action_str = action_str.strip()

            # Clean up common LLM artefacts
            if action_str.startswith("```"):
                action_str = action_str.strip("`").strip()
                if action_str.lower().startswith("python"):
                    action_str = action_str[6:].strip()
            # Remove any trailing explanation after the command
            for sep in ["\n", "  #", " //", " --"]:
                if sep in action_str:
                    action_str = action_str[: action_str.index(sep)].strip()

            # Step the environment
            obs = env.step(IncidentAction(command=action_str))
            reward = float(obs.reward) if obs.reward is not None else 0.0
            done = obs.done
            error = obs.last_action_error

            rewards.append(reward)

            error_str = error if error else "null"
            done_str = "true" if done else "false"
            print(
                f"[STEP] step={step_num} action={action_str} "
                f"reward={reward:.2f} done={done_str} error={error_str}"
            )

            if done:
                break

            # Update conversation
            messages.append({"role": "assistant", "content": action_str})
            messages.append({"role": "user", "content": obs.output})

        success = obs.score >= 0.5
        rewards_str = ",".join(f"{r:.2f}" for r in rewards)
        print(
            f"[END] success={'true' if success else 'false'} "
            f"steps={len(rewards)} rewards={rewards_str}"
        )

    except Exception:
        # [END] MUST always be emitted
        rewards_str = ",".join(f"{r:.2f}" for r in rewards) if rewards else "0.00"
        print(
            f"[END] success=false steps={len(rewards)} rewards={rewards_str}"
        )
        traceback.print_exc(file=sys.stderr)


def main() -> None:
    for task in TASKS:
        run_task(task)


if __name__ == "__main__":
    main()
