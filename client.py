"""Client for connecting to the SRE Incident Response Environment server.

Provides two implementations:

1. **IncidentEnvClient** (WebSocket, via *openenv-core*) -- used when the
   ``openenv`` package is installed.
2. **IncidentEnvClient** (HTTP fallback) -- a lightweight ``requests``-based
   client that talks to the REST endpoints exposed by ``server/app.py``.

Both expose the same public surface (``reset``, ``step``, ``state``, ``close``)
so calling code does not need to branch.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import IncidentAction, IncidentObservation

# ---------------------------------------------------------------------------
# Try the official openenv client first
# ---------------------------------------------------------------------------
_HAS_OPENENV = False
try:
    from openenv.core import EnvClient, StepResult
    from openenv.core.env_server.types import State

    _HAS_OPENENV = True
except ImportError:
    pass

if _HAS_OPENENV:

    class IncidentEnvClient(EnvClient[IncidentObservation, State, IncidentAction]):
        """WebSocket client for the Incident Response Environment.

        Wraps the generic ``EnvClient`` and provides typed serialisation /
        deserialisation for :class:`IncidentAction` and
        :class:`IncidentObservation`.
        """

        def _step_payload(self, action: IncidentAction) -> Dict[str, Any]:
            """Serialise an action into the wire format expected by the server."""
            return {"command": action.command}

        def _parse_result(self, data: Dict[str, Any]) -> StepResult[IncidentObservation]:
            """Deserialise a server response into a typed ``StepResult``."""
            obs_data = data.get("observation", data)
            obs = IncidentObservation(**obs_data)
            return StepResult(
                observation=obs,
                reward=data.get("reward"),
                done=data.get("done", False),
            )

        def _parse_state(self, data: Dict[str, Any]) -> State:
            """Deserialise server state."""
            return State(**data)

else:
    # ------------------------------------------------------------------
    # Fallback: pure-HTTP client using requests
    # ------------------------------------------------------------------
    try:
        import requests as _requests
    except ImportError:
        _requests = None  # type: ignore[assignment]

    class IncidentEnvClient:  # type: ignore[no-redef]
        """HTTP client fallback when *openenv-core* is not installed.

        Connects to the REST endpoints served by ``server/app.py``'s fallback
        FastAPI application.

        Usage::

            client = IncidentEnvClient("http://localhost:8000")
            obs = client.reset(task="service_crash")
            while not obs.get("done"):
                obs = client.step("check_status('api-gateway')")
            client.close()
        """

        def __init__(self, base_url: str = "http://localhost:8000") -> None:
            if _requests is None:
                raise RuntimeError(
                    "The 'requests' package is required for the HTTP fallback client. "
                    "Install it with: pip install requests"
                )
            self.base_url = base_url.rstrip("/")
            self.session = _requests.Session()
            self.session_id: Optional[str] = None

        # ---- public API --------------------------------------------------

        def reset(self, task: str = "service_crash", **kwargs: Any) -> Dict[str, Any]:
            """Reset the environment and return the initial observation."""
            payload: Dict[str, Any] = {
                "task": task,
                "episode_id": kwargs.get("episode_id"),
                "seed": kwargs.get("seed"),
                "session_id": self.session_id,
            }
            resp = self.session.post(f"{self.base_url}/reset", json=payload)
            resp.raise_for_status()
            data = resp.json()
            self.session_id = data.get("session_id", self.session_id)
            return data.get("observation", data)

        def step(self, action: Any) -> Dict[str, Any]:
            """Send a command and return the observation dict.

            ``action`` may be an :class:`IncidentAction`, a plain ``str``
            (interpreted as the command), or a ``dict`` with a ``"command"``
            key.
            """
            if isinstance(action, IncidentAction):
                command = action.command
            elif isinstance(action, str):
                command = action
            elif isinstance(action, dict):
                command = action.get("command", "")
            else:
                command = str(action)

            payload: Dict[str, Any] = {
                "action": {"command": command},
                "session_id": self.session_id,
            }
            resp = self.session.post(f"{self.base_url}/step", json=payload)
            resp.raise_for_status()
            data = resp.json()
            self.session_id = data.get("session_id", self.session_id)
            return data.get("observation", data)

        def state(self) -> Dict[str, Any]:
            """Return the current environment state."""
            params: Dict[str, str] = {}
            if self.session_id:
                params["session_id"] = self.session_id
            resp = self.session.get(f"{self.base_url}/state", params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("state", data)

        def health(self) -> Dict[str, Any]:
            """Hit the ``/health`` endpoint."""
            resp = self.session.get(f"{self.base_url}/health")
            resp.raise_for_status()
            return resp.json()

        def list_scenarios(self) -> Dict[str, Any]:
            """Fetch available scenarios from ``/scenarios``."""
            resp = self.session.get(f"{self.base_url}/scenarios")
            resp.raise_for_status()
            return resp.json()

        def close(self) -> None:
            """Close the HTTP session (and optionally delete the server-side session)."""
            if self.session_id:
                try:
                    self.session.delete(f"{self.base_url}/session/{self.session_id}")
                except Exception:
                    pass  # best-effort cleanup
            self.session.close()

        # context-manager support
        def __enter__(self) -> "IncidentEnvClient":
            return self

        def __exit__(self, *exc: Any) -> None:
            self.close()
