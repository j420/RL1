"""FastAPI application for the SRE Incident Response Environment.

This module provides the HTTP entry-point.  When *openenv-core* is installed the
official ``create_app`` helper is used.  Otherwise a fully-functional fallback
FastAPI application is created so the environment can be tested and deployed
without the openenv wheel.
"""

from __future__ import annotations

import os
import sys
import uuid
from typing import Any, Dict, Optional

# Ensure the project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.environment import IncidentEnvironment
from models import IncidentAction, IncidentObservation

# ---------------------------------------------------------------------------
# Try the official openenv helper first
# ---------------------------------------------------------------------------
_openenv_available = False
try:
    from openenv.core.env_server.http_server import create_app

    app = create_app(
        env_class=IncidentEnvironment,
        action_type=IncidentAction,
        observation_type=IncidentObservation,
        env_name="incident_response",
        max_concurrent_envs=10,
        enable_web_interface=True,
    )
    _openenv_available = True
except Exception:
    _openenv_available = False

# ---------------------------------------------------------------------------
# Fallback: minimal FastAPI app that exposes the same REST surface
# ---------------------------------------------------------------------------
if not _openenv_available:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel

    app = FastAPI(
        title="SRE Incident Response Environment",
        description="OpenEnv-compatible REST API for incident response training",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- session store --------------------------------------------------
    _sessions: Dict[str, IncidentEnvironment] = {}
    _default_session_id: Optional[str] = None

    def _get_or_create_env(session_id: Optional[str] = None) -> tuple[str, IncidentEnvironment]:
        """Return an existing session or create a new one."""
        nonlocal _default_session_id
        if session_id and session_id in _sessions:
            return session_id, _sessions[session_id]
        sid = session_id or _default_session_id or str(uuid.uuid4())
        if sid not in _sessions:
            _sessions[sid] = IncidentEnvironment()
        _default_session_id = sid
        return sid, _sessions[sid]

    # ---- request / response models --------------------------------------
    class ResetRequest(BaseModel):
        episode_id: Optional[str] = None
        seed: Optional[int] = None
        task: str = "service_crash"
        session_id: Optional[str] = None

    class StepRequest(BaseModel):
        action: Dict[str, Any]
        session_id: Optional[str] = None

    class StateRequest(BaseModel):
        session_id: Optional[str] = None

    # ---- endpoints -------------------------------------------------------
    @app.get("/health")
    async def health() -> Dict[str, Any]:
        """Liveness / readiness probe."""
        return {
            "status": "healthy",
            "environment": "incident_response",
            "openenv_core": False,
            "active_sessions": len(_sessions),
        }

    @app.post("/reset")
    async def reset(req: ResetRequest) -> Dict[str, Any]:
        """Reset (or create) an environment session and return the first observation."""
        session_id, env = _get_or_create_env(req.session_id)
        obs = env.reset(
            seed=req.seed,
            episode_id=req.episode_id,
            task=req.task,
        )
        return {
            "session_id": session_id,
            "observation": obs.model_dump(),
        }

    @app.post("/step")
    async def step(req: StepRequest) -> Dict[str, Any]:
        """Execute one action in the environment."""
        session_id, env = _get_or_create_env(req.session_id)
        if env._simulation is None:
            raise HTTPException(
                status_code=400,
                detail="Environment not initialised. Call /reset first.",
            )
        command = req.action.get("command", "")
        if not command:
            raise HTTPException(status_code=422, detail="Missing 'command' in action")
        action = IncidentAction(command=command)
        obs = env.step(action)
        return {
            "session_id": session_id,
            "observation": obs.model_dump(),
            "reward": obs.reward,
            "done": obs.done,
        }

    @app.get("/state")
    async def get_state(session_id: Optional[str] = None) -> Dict[str, Any]:
        """Return the current environment state."""
        sid, env = _get_or_create_env(session_id)
        return {
            "session_id": sid,
            "state": env.state.model_dump(),
        }

    @app.get("/scenarios")
    async def list_scenarios() -> Dict[str, Any]:
        """List available incident scenarios."""
        from server.scenarios import SCENARIOS

        return {
            "scenarios": {
                name: {
                    "name": sc.name,
                    "difficulty": sc.difficulty,
                    "max_steps": sc.max_steps,
                    "description": sc.description,
                }
                for name, sc in SCENARIOS.items()
            }
        }

    @app.delete("/session/{session_id}")
    async def delete_session(session_id: str) -> Dict[str, str]:
        """Delete a session and free its resources."""
        if session_id in _sessions:
            del _sessions[session_id]
            return {"status": "deleted", "session_id": session_id}
        raise HTTPException(status_code=404, detail="Session not found")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------
def main() -> None:
    """Run the server with uvicorn."""
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    reload = os.environ.get("RELOAD", "").lower() in ("1", "true", "yes")
    uvicorn.run(
        "server.app:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    main()
