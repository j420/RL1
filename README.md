# SRE Incident Response Environment

An [OpenEnv](https://github.com/meta-pytorch/OpenEnv)-compatible environment that simulates **real-world production incident response**. An AI agent takes the role of an on-call Site Reliability Engineer, diagnosing and fixing incidents in a microservice architecture through text-based investigation commands.

---

## Environment Overview

Production incidents cost companies billions of dollars annually. Skilled incident response — quickly diagnosing root causes and applying correct fixes — is one of the most valuable skills in modern software engineering.

This environment simulates a realistic microservice platform with services experiencing various failure modes: OOM crashes, cascading failures from misconfigurations, memory leaks, expiring certificates, and bad deployments with race conditions. The agent must investigate by reading logs, checking metrics, tracing dependencies, and then applying the right remediation.

**Why this matters:** Training AI agents to perform SRE tasks can reduce mean-time-to-resolution (MTTR) from hours to minutes, directly reducing revenue loss and improving service reliability.

---

## Action Space

The agent sends text commands as actions. Each command returns realistic monitoring output.

| Command | Description | Example |
|---------|-------------|---------|
| `list_services()` | Overview of all services with status and metrics | `list_services()` |
| `check_status(svc)` | Detailed status of a single service | `check_status('api-gateway')` |
| `read_logs(svc, lines=N)` | Recent log entries (default: all available) | `read_logs('user-service', lines=20)` |
| `check_metrics(svc, metric)` | Time-series metric data | `check_metrics('database', 'cpu')` |
| `check_dependencies(svc)` | Dependency tree with health status | `check_dependencies('api-gateway')` |
| `restart_service(svc)` | Restart a service | `restart_service('cache-service')` |
| `scale_service(svc, N)` | Scale to N replicas | `scale_service('api-gateway', 3)` |
| `rollback_deployment(svc)` | Rollback to previous version | `rollback_deployment('user-service')` |
| `update_config(svc, key, val)` | Update a configuration parameter | `update_config('cache-service', 'maxmemory', '512mb')` |
| `run_healthcheck(svc)` | Comprehensive health check | `run_healthcheck('api-gateway')` |
| `diagnose(desc)` | Record root-cause diagnosis | `diagnose('OOM from bad deploy')` |

Available metrics: `cpu`, `memory`, `latency`, `error_rate`, `connections`

---

## Observation Space

| Field | Type | Description |
|-------|------|-------------|
| `output` | `str` | Text output from the last command (logs, metrics, status reports) |
| `incident_summary` | `str` | The original incident alert description |
| `services` | `List[str]` | Names of all services in the system |
| `available_commands` | `List[str]` | List of available command signatures |
| `step_count` | `int` | Current step number |
| `max_steps` | `int` | Maximum steps before episode ends |
| `score` | `float` | Cumulative score (0.0 - 1.0) |
| `task_name` | `str` | Current task identifier |
| `done` | `bool` | Whether the episode has ended |
| `reward` | `float` | Step reward (milestone delta) or final score |
| `last_action_error` | `str or None` | Error message if the command failed |
| `metadata` | `dict` | Contains `reward_breakdown` with structured scoring |

---

## Reward Structure

The environment uses **milestone-based grading** with partial progress signals at every step.

### Reward Components
- **Investigation** (~0.20-0.30): Checking status, reading logs, and examining metrics of affected services
- **Diagnosis** (~0.10-0.15): Submitting an accurate root-cause diagnosis
- **Remediation** (~0.35-0.40): Applying the correct fix (rollback, config update, restart)
- **Efficiency Bonus** (up to 0.10): Solving the incident in fewer steps

### Penalties
- **Repeating commands**: -0.01 per repeated command
- **Destructive action on healthy service**: -0.03 (restart/rollback/scale a healthy service)
- **Invalid command**: -0.005
- **Maximum cumulative penalty**: -0.15

### Score Range
- Final scores are clamped to **[0.001, 0.999]**
- Scores above 0.5 indicate successful incident resolution
- The reward breakdown is available in `observation.metadata["reward_breakdown"]`

---

## Tasks

### 1. `service_crash` (Easy) — 15 steps max

**Scenario:** The `user-service` has crashed with an OutOfMemoryError after a bad deployment (`v2.5.0-rc1`). The `api-gateway` is returning 502 errors for user-related endpoints.

**Root Cause:** OOM crash caused by a memory-hungry cache preload in the new deployment.

**Expected Solution:** `rollback_deployment('user-service')`

**Grading:** Investigation (0.25) + Remediation (0.40) + Efficiency bonus (0.10)

### 2. `cascading_failure` (Medium) — 25 steps max

**Scenario:** Widespread service degradation. The `cache-service` was misconfigured with `maxmemory=32mb` (should be `512mb`), causing a cache eviction storm. All reads miss the cache and hit the database directly, exhausting its connection pool and causing cascading timeouts across `auth-service`, `user-service`, and `order-service`.

**Root Cause:** Cache `maxmemory` set too low, causing near-zero hit rate.

**Expected Solution:** `update_config('cache-service', 'maxmemory', '512mb')` followed by `restart_service('cache-service')`

**Grading:** Investigation (0.30) + Remediation (0.35) + Verification (0.20) + Efficiency (0.10)

### 3. `multi_factor_degradation` (Hard) — 40 steps max

**Scenario:** Three independent root causes affecting the platform simultaneously:

1. **api-gateway**: Memory leak caused by `verbose_logging=true` config (memory at 82% and climbing)
2. **auth-service**: SSL certificate expiring in 2 hours, causing intermittent TLS handshake failures
3. **payment-service**: Bad deployment `v1.9.0-beta` introduced a race condition in transaction processing

**Expected Solutions:**
1. `update_config('api-gateway', 'verbose_logging', 'false')`
2. `update_config('auth-service', 'ssl_cert_path', '/certs/renewed/server.pem')`
3. `rollback_deployment('payment-service')`

**Grading:** 0.30 per root cause (investigation + fix) + 0.10 efficiency bonus

---

## Setup Instructions

### Prerequisites
- Python 3.10+
- pip

### Install

```bash
pip install -e .
# Or install dependencies directly:
pip install "openenv-core[core]>=0.2.2" fastapi pydantic uvicorn requests openai
```

### Run the Server

```bash
# With openenv-core
uvicorn server.app:app --host 0.0.0.0 --port 8000

# Or use the CLI entry point
python -m server.app
```

### Run the Baseline Inference

```bash
export HF_TOKEN="your-api-token"
export API_BASE_URL="https://api-inference.huggingface.co/v1"
export MODEL_NAME="Qwen/Qwen2.5-72B-Instruct"

python inference.py
```

### Run Tests

```bash
pip install pytest
python -m pytest server/test_environment.py -v
```

---

## Baseline Performance Scores

| Task | Difficulty | Expected Score | Steps |
|------|-----------|---------------|-------|
| `service_crash` | Easy | 0.70 - 0.85 | 4-6 |
| `cascading_failure` | Medium | 0.50 - 0.70 | 6-10 |
| `multi_factor_degradation` | Hard | 0.40 - 0.65 | 9-15 |

Scores are deterministic given the same sequence of actions.

---

## Docker Deployment

```bash
# Build
docker build -f server/Dockerfile -t incident-response-env .

# Run
docker run -p 7860:7860 incident-response-env

# Verify
curl http://localhost:7860/health
```

---

## Hugging Face Spaces

Deploy as a Docker Space on Hugging Face:

1. Create a new Space with **Docker** SDK
2. Upload all files
3. Tag the Space with `openenv`
4. The Dockerfile exposes port 7860 (HF Spaces requirement)

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_BASE_URL` | `https://api.openai.com/v1` | LLM API endpoint |
| `MODEL_NAME` | `gpt-4.1-mini` | Model identifier |
| `HF_TOKEN` | *(required)* | API authentication token |
| `PORT` | `8000` | Server port |
| `HOST` | `0.0.0.0` | Server bind address |

---

## Architecture

```
├── models.py              # Pydantic Action/Observation/Reward models
├── client.py              # OpenEnv client (WebSocket + HTTP fallback)
├── openenv.yaml           # OpenEnv manifest
├── pyproject.toml         # Dependencies
├── inference.py           # Baseline LLM inference script
├── server/
│   ├── app.py             # FastAPI server (OpenEnv + fallback)
│   ├── environment.py     # IncidentEnvironment (reset/step/state)
│   ├── simulation.py      # Command execution engine
│   ├── scenarios.py       # 3 scenario definitions
│   ├── grader.py          # Milestone-based grading
│   ├── Dockerfile         # HF Spaces deployment
│   └── test_environment.py
└── README.md
```

---

## Programmatic Usage

```python
from server.environment import IncidentEnvironment
from models import IncidentAction

env = IncidentEnvironment()
obs = env.reset(task="service_crash")

print(obs.output)  # Incident alert

obs = env.step(IncidentAction(command="list_services()"))
print(obs.output)  # Service table

obs = env.step(IncidentAction(command="read_logs('user-service')"))
print(obs.output)  # Log entries showing OOM crash

obs = env.step(IncidentAction(command="rollback_deployment('user-service')"))
print(f"Score: {obs.score}, Done: {obs.done}")  # Score: ~0.7, Done: True
```
