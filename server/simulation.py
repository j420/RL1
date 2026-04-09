"""Simulation engine for the SRE Incident Response Environment.

Maintains the live state of all services and executes agent commands against
them.  Each command returns formatted text output that mimics real monitoring
and operations tooling.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from server.scenarios import RootCause, Scenario, ServiceDefinition


# ---------------------------------------------------------------------------
# Command parser
# ---------------------------------------------------------------------------

def _parse_command(raw: str) -> Tuple[str, List[str], Dict[str, str]]:
    """Parse a function-call-style command string.

    Returns ``(name, positional_args, keyword_args)``.

    Examples::

        "list_services()"                     -> ("list_services", [], {})
        "check_status('api-gateway')"         -> ("check_status", ["api-gateway"], {})
        "read_logs('svc', lines=20)"          -> ("read_logs", ["svc"], {"lines": "20"})
        "update_config('svc', 'key', 'val')"  -> ("update_config", ["svc", "key", "val"], {})
    """
    raw = raw.strip()
    # Match:  command_name(...)
    m = re.match(r"^(\w+)\s*\((.*)\)\s*$", raw, re.DOTALL)
    if not m:
        raise ValueError(f"Could not parse command: {raw}")

    name = m.group(1)
    args_str = m.group(2).strip()

    if not args_str:
        return name, [], {}

    positional: List[str] = []
    kwargs: Dict[str, str] = {}

    # Tokenise on commas that are NOT inside quotes
    tokens: List[str] = []
    current = ""
    in_quote: Optional[str] = None
    for ch in args_str:
        if ch in ("'", '"') and in_quote is None:
            in_quote = ch
        elif ch == in_quote:
            in_quote = None
        elif ch == "," and in_quote is None:
            tokens.append(current.strip())
            current = ""
            continue
        current += ch
    if current.strip():
        tokens.append(current.strip())

    for token in tokens:
        token = token.strip()
        # kwarg?  e.g. lines=20
        kv = re.match(r"^(\w+)\s*=\s*(.+)$", token)
        if kv:
            kwargs[kv.group(1)] = _strip_quotes(kv.group(2).strip())
        else:
            positional.append(_strip_quotes(token))

    return name, positional, kwargs


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in ("'", '"') and s[-1] == s[0]:
        return s[1:-1]
    return s


# ---------------------------------------------------------------------------
# Main simulation class
# ---------------------------------------------------------------------------

VALID_METRICS = {"cpu", "memory", "latency", "error_rate", "connections"}

VALID_COMMANDS = {
    "list_services",
    "check_status",
    "read_logs",
    "check_metrics",
    "check_dependencies",
    "restart_service",
    "scale_service",
    "rollback_deployment",
    "update_config",
    "run_healthcheck",
    "diagnose",
}


class ServiceSimulation:
    """Stateful simulation of a microservice cluster during an incident."""

    def __init__(self, scenario: Scenario) -> None:
        # Deep-copy so mutations don't touch the shared template
        self._scenario = scenario
        self._services: Dict[str, ServiceDefinition] = {
            name: copy.deepcopy(svc) for name, svc in scenario.services.items()
        }
        self._root_causes: List[Dict[str, Any]] = []
        for rc in scenario.root_causes:
            self._root_causes.append({
                "rc": rc,
                "resolved": False,
                "config_applied": False,
                "restarted": False,
            })

        self._command_history: List[str] = []
        self._services_investigated: Set[str] = set()
        self._services_logs_read: Set[str] = set()
        self._services_metrics_read: Set[str] = set()
        self._services_deps_checked: Set[str] = set()
        self._services_healthchecked: Set[str] = set()
        self._services_restarted: Set[str] = set()
        self._services_rolled_back: Set[str] = set()
        self._services_config_updated: Dict[str, Dict[str, str]] = {}
        self._diagnoses: List[str] = []
        self._achieved_milestones: Set[str] = set()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def execute_command(self, command_str: str) -> Tuple[str, Optional[str]]:
        """Parse and execute a command.  Returns ``(output, error_or_none)``."""
        self._command_history.append(command_str)

        try:
            name, args, kwargs = _parse_command(command_str)
        except ValueError:
            return "", (
                f"Could not parse command. Expected function-call syntax.\n"
                f"Available commands: {', '.join(sorted(VALID_COMMANDS))}"
            )

        if name not in VALID_COMMANDS:
            return "", (
                f"Unknown command: {name}\n"
                f"Available commands: {', '.join(sorted(VALID_COMMANDS))}"
            )

        handler = getattr(self, f"_cmd_{name}", None)
        if handler is None:
            return "", f"Command not implemented: {name}"

        try:
            output = handler(args, kwargs)
            self._update_milestones(name, args, kwargs)
            return output, None
        except Exception as exc:  # noqa: BLE001
            return "", str(exc)

    def get_service_names(self) -> List[str]:
        return sorted(self._services.keys())

    def is_fully_resolved(self) -> bool:
        return all(rc["resolved"] for rc in self._root_causes)

    def get_achieved_milestones(self) -> Set[str]:
        return set(self._achieved_milestones)

    def get_command_history(self) -> List[str]:
        return list(self._command_history)

    # ------------------------------------------------------------------
    # Milestone tracking
    # ------------------------------------------------------------------

    def _update_milestones(self, cmd: str, args: List[str], kwargs: Dict[str, str]) -> None:
        """Check investigation_milestones from the scenario and add any that
        are now satisfied."""
        milestones = self._scenario.investigation_milestones

        if cmd == "list_services" and "list_services" in milestones:
            self._achieved_milestones.add("list_services")

        if args:
            svc = args[0]
            # Try full command name and shortened forms
            # e.g. rollback_deployment -> rollback, restart_service -> restart
            candidates = [f"{cmd}_{svc}"]
            short_map = {
                "rollback_deployment": "rollback",
                "restart_service": "restart",
                "scale_service": "scale",
            }
            if cmd in short_map:
                candidates.append(f"{short_map[cmd]}_{svc}")

            for key in candidates:
                if key in milestones:
                    self._achieved_milestones.add(key)

    # ------------------------------------------------------------------
    # Command implementations
    # ------------------------------------------------------------------

    def _cmd_list_services(self, args: List[str], kwargs: Dict[str, str]) -> str:
        header = (
            f"{'Service':<25} {'Status':<12} {'CPU':>7} {'Memory':>8} "
            f"{'Latency':>10} {'ErrRate':>8} {'Conns':>8}"
        )
        sep = "-" * len(header)
        lines = [header, sep]
        for name in sorted(self._services):
            s = self._services[name]
            lat = f"{s.latency:.0f}ms" if s.status != "down" else "N/A"
            lines.append(
                f"{name:<25} {s.status.upper():<12} {s.cpu:>6.1f}% "
                f"{s.memory:>6.1f}% {lat:>10} {s.error_rate:>6.1f}% "
                f"{s.connections:>8}"
            )
        return "\n".join(lines)

    def _cmd_check_status(self, args: List[str], kwargs: Dict[str, str]) -> str:
        svc = self._require_service(args)
        s = self._services[svc]
        self._services_investigated.add(svc)

        lat = f"{s.latency:.0f} ms" if s.status != "down" else "N/A"
        mem_gb = s.memory / 100 * 8  # assume 8GB total
        cfg_lines = "\n".join(f"    {k}: {v}" for k, v in s.config.items()) if s.config else "    (default)"

        # Determine previous version text
        prev = "N/A"
        for rc_info in self._root_causes:
            rc: RootCause = rc_info["rc"]
            if rc.service == svc and rc.fix_type == "rollback":
                # The logs already mention the previous version for the root cause services
                pass
        # Try to extract from logs
        for log_line in reversed(s.logs):
            if "last healthy" in log_line.lower() or "last stable" in log_line.lower():
                m = re.search(r"v[\d]+\.[\d]+[.\w-]*", log_line)
                if m:
                    prev = m.group(0)
                    break

        return (
            f"=== Service Status: {svc} ===\n"
            f"Status:          {s.status.upper()}\n"
            f"CPU Usage:       {s.cpu:.1f}%\n"
            f"Memory Usage:    {s.memory:.1f}% ({mem_gb:.1f} GB / 8.0 GB)\n"
            f"Latency (p99):   {lat}\n"
            f"Error Rate:      {s.error_rate:.1f}%\n"
            f"Connections:     {s.connections}\n"
            f"Version:         {s.deployment_version}\n"
            f"Health Check:    {'PASS' if s.healthcheck_ok else 'FAIL'}\n"
            f"Dependencies:    {', '.join(s.dependencies) if s.dependencies else 'none'}\n"
            f"Config:\n{cfg_lines}"
        )

    def _cmd_read_logs(self, args: List[str], kwargs: Dict[str, str]) -> str:
        svc = self._require_service(args)
        s = self._services[svc]
        self._services_logs_read.add(svc)

        num_lines = min(int(kwargs.get("lines", "50")), len(s.logs))
        log_entries = s.logs[-num_lines:] if s.logs else ["(no log entries available)"]
        header = f"=== Logs: {svc} (last {num_lines} entries) ===\n"
        return header + "\n".join(log_entries)

    def _cmd_check_metrics(self, args: List[str], kwargs: Dict[str, str]) -> str:
        if len(args) < 2:
            raise ValueError(
                "check_metrics requires two arguments: service_name and metric_name.\n"
                f"Available metrics: {', '.join(sorted(VALID_METRICS))}"
            )
        svc = self._require_service(args)
        metric = args[1].lower()
        if metric not in VALID_METRICS:
            raise ValueError(
                f"Unknown metric: {metric}\n"
                f"Available metrics: {', '.join(sorted(VALID_METRICS))}"
            )
        s = self._services[svc]
        self._services_metrics_read.add(svc)

        value_map = {
            "cpu": (s.cpu, "%"),
            "memory": (s.memory, "%"),
            "latency": (s.latency, "ms"),
            "error_rate": (s.error_rate, "%"),
            "connections": (float(s.connections), ""),
        }
        val, unit = value_map[metric]

        # Generate a simple sparkline-style view
        lines = [f"=== Metrics: {svc} / {metric} ==="]
        lines.append(f"Current:  {val:.1f}{unit}")

        # Simulate a 30-min trend
        import random
        rng = random.Random(hash(svc + metric))
        points = []
        for i in range(6):
            noise = rng.uniform(-5, 5)
            p = max(0, val + noise - (5 - i) * (rng.uniform(0, 2)))
            points.append(p)
        points.append(val)

        max_val = max(points) if points else 1
        bar_width = 30
        lines.append(f"\nTrend (last 30 min):")
        for i, p in enumerate(points):
            t_min = i * 5
            filled = int((p / max(max_val, 0.01)) * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            lines.append(f"  T-{30 - t_min:>2}m  {bar}  {p:.1f}{unit}")

        lines.append(f"\nAverage: {sum(points) / len(points):.1f}{unit}")
        lines.append(f"Peak:    {max(points):.1f}{unit}")

        return "\n".join(lines)

    def _cmd_check_dependencies(self, args: List[str], kwargs: Dict[str, str]) -> str:
        svc = self._require_service(args)
        self._services_deps_checked.add(svc)
        return self._build_dep_tree(svc, indent=0, visited=set())

    def _build_dep_tree(self, svc: str, indent: int, visited: Set[str]) -> str:
        if svc in visited:
            return " " * indent + f"└── {svc} (circular ref)\n"
        visited.add(svc)
        s = self._services.get(svc)
        if s is None:
            return " " * indent + f"└── {svc} (unknown)\n"

        prefix = "    " * indent
        connector = "├── " if indent > 0 else ""
        line = f"{prefix}{connector}{svc} [{s.status.upper()}]\n"
        for dep in s.dependencies:
            line += self._build_dep_tree(dep, indent + 1, visited)
        return line

    def _cmd_restart_service(self, args: List[str], kwargs: Dict[str, str]) -> str:
        svc = self._require_service(args)
        s = self._services[svc]
        self._services_restarted.add(svc)

        # Check if any root cause is resolved by restart alone
        fixed_something = False
        for rc_info in self._root_causes:
            rc: RootCause = rc_info["rc"]
            if rc.service == svc and not rc_info["resolved"]:
                if rc.fix_type == "restart":
                    rc_info["resolved"] = True
                    fixed_something = True
                elif rc.fix_type == "update_config" and rc_info["config_applied"]:
                    # Config was already updated, restart completes the fix
                    rc_info["resolved"] = True
                    rc_info["restarted"] = True
                    fixed_something = True
                else:
                    rc_info["restarted"] = True

        if fixed_something:
            self._heal_service(svc)
            return (
                f"Restarting service: {svc}...\n"
                f"Service {svc} restarted successfully.\n"
                f"Current status: HEALTHY"
            )
        else:
            # Restart doesn't fix the root cause
            status = s.status.upper()
            return (
                f"Restarting service: {svc}...\n"
                f"Service {svc} restarted.\n"
                f"Current status: {status} (underlying issue may persist)"
            )

    def _cmd_scale_service(self, args: List[str], kwargs: Dict[str, str]) -> str:
        svc = self._require_service(args)
        replicas = int(args[1]) if len(args) > 1 else 2
        return (
            f"Scaling service: {svc} to {replicas} replicas...\n"
            f"Service {svc} scaled to {replicas} replicas.\n"
            f"Note: Scaling does not fix underlying root causes."
        )

    def _cmd_rollback_deployment(self, args: List[str], kwargs: Dict[str, str]) -> str:
        svc = self._require_service(args)
        s = self._services[svc]
        self._services_rolled_back.add(svc)

        old_version = s.deployment_version

        # Check if rollback fixes a root cause
        fixed = False
        for rc_info in self._root_causes:
            rc: RootCause = rc_info["rc"]
            if rc.service == svc and rc.fix_type == "rollback" and not rc_info["resolved"]:
                rc_info["resolved"] = True
                fixed = True

        if fixed:
            # Find previous version from logs
            prev_version = "previous"
            for log_line in s.logs:
                if "last healthy" in log_line.lower() or "last stable" in log_line.lower():
                    m = re.search(r"v[\d]+\.[\d]+[.\w-]*", log_line)
                    if m:
                        prev_version = m.group(0)
                        break
            s.deployment_version = prev_version
            self._heal_service(svc)
            self._propagate_healing()
            return (
                f"Rolling back service: {svc}...\n"
                f"Deployment rolled back: {old_version} -> {prev_version}\n"
                f"Service {svc} is now HEALTHY."
            )
        else:
            return (
                f"Rolling back service: {svc}...\n"
                f"Deployment rolled back to previous version.\n"
                f"Note: This service's issue may not be deployment-related."
            )

    def _cmd_update_config(self, args: List[str], kwargs: Dict[str, str]) -> str:
        if len(args) < 3:
            raise ValueError(
                "update_config requires three arguments: service_name, key, value"
            )
        svc = self._require_service(args)
        key = args[1]
        value = args[2]
        s = self._services[svc]

        old_value = s.config.get(key, "(not set)")
        s.config[key] = value

        if svc not in self._services_config_updated:
            self._services_config_updated[svc] = {}
        self._services_config_updated[svc][key] = value

        # Check if this config change matches a root cause fix
        for rc_info in self._root_causes:
            rc: RootCause = rc_info["rc"]
            if (rc.service == svc and rc.fix_type == "update_config"
                    and not rc_info["resolved"]):
                expected_key = rc.fix_args.get("key", "")
                expected_value = rc.fix_args.get("value", "")
                if key == expected_key and value.lower() == expected_value.lower():
                    rc_info["config_applied"] = True
                    # Some configs take effect immediately, some need restart
                    # For simplicity: config changes that don't need restart resolve immediately
                    # if the service was already restarted, or if no restart is needed
                    # For this environment, update_config alone resolves the root cause
                    rc_info["resolved"] = True
                    self._heal_service(svc)
                    self._propagate_healing()
                    return (
                        f"Configuration updated: {svc}\n"
                        f"  {key}: {old_value} -> {value}\n"
                        f"Config applied successfully. Service {svc} is now HEALTHY."
                    )

        return (
            f"Configuration updated: {svc}\n"
            f"  {key}: {old_value} -> {value}\n"
            f"Note: Change applied. May require restart to take full effect."
        )

    def _cmd_run_healthcheck(self, args: List[str], kwargs: Dict[str, str]) -> str:
        svc = self._require_service(args)
        s = self._services[svc]
        self._services_healthchecked.add(svc)

        checks = [
            ("Process Running", s.status != "down"),
            ("Port Responding", s.status != "down"),
            ("Memory OK", s.memory < 90),
            ("CPU OK", s.cpu < 90),
            ("Error Rate OK", s.error_rate < 5),
            ("Latency OK", s.latency < 500 or s.status == "down"),
            ("Dependencies Reachable", all(
                self._services.get(d, ServiceDefinition(name=d)).status != "down"
                for d in s.dependencies
            )),
        ]

        lines = [f"=== Health Check: {svc} ==="]
        all_pass = True
        for check_name, passed in checks:
            icon = "PASS" if passed else "FAIL"
            lines.append(f"  [{icon}] {check_name}")
            if not passed:
                all_pass = False

        overall = "HEALTHY" if all_pass else ("DEGRADED" if s.status != "down" else "DOWN")
        lines.append(f"\nOverall: {overall}")
        return "\n".join(lines)

    def _cmd_diagnose(self, args: List[str], kwargs: Dict[str, str]) -> str:
        if not args:
            raise ValueError("diagnose requires a description argument")
        desc = " ".join(args)
        self._diagnoses.append(desc)
        return (
            f"Diagnosis recorded: {desc}\n\n"
            f"Continue investigating or apply fixes based on your diagnosis."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_service(self, args: List[str]) -> str:
        if not args:
            raise ValueError(
                "This command requires a service name.\n"
                f"Available services: {', '.join(sorted(self._services))}"
            )
        svc = args[0]
        if svc not in self._services:
            raise ValueError(
                f"Service not found: {svc}\n"
                f"Available services: {', '.join(sorted(self._services))}"
            )
        return svc

    def _heal_service(self, svc: str) -> None:
        """Reset a service to healthy metrics after its root cause is fixed."""
        s = self._services[svc]
        s.status = "healthy"
        s.cpu = 15.0
        s.memory = 40.0
        s.latency = 50.0
        s.error_rate = 0.1
        s.healthcheck_ok = True
        s.is_root_cause = False

    def _propagate_healing(self) -> None:
        """When a root-cause service heals, downstream services may recover too."""
        # Simple: if all root causes for a scenario are fixed, heal everything
        if self.is_fully_resolved():
            for s in self._services.values():
                if s.status != "healthy":
                    s.status = "healthy"
                    s.cpu = max(s.cpu * 0.5, 15.0)
                    s.memory = max(s.memory * 0.5, 40.0)
                    s.latency = min(s.latency * 0.3, 100.0)
                    s.error_rate = max(s.error_rate * 0.1, 0.1)
                    s.healthcheck_ok = True
        else:
            # Partial healing: heal services whose direct root cause is fixed
            resolved_services = {
                rc_info["rc"].service
                for rc_info in self._root_causes
                if rc_info["resolved"]
            }
            for name, s in self._services.items():
                if name in resolved_services:
                    continue  # already healed
                # If a service depends only on healed services, improve it
                if s.status != "healthy" and not s.is_root_cause:
                    deps_ok = all(
                        self._services.get(d, ServiceDefinition(name=d)).status == "healthy"
                        for d in s.dependencies
                    )
                    if deps_ok:
                        # Partial improvement
                        s.error_rate = max(s.error_rate * 0.5, 0.5)
                        s.latency = max(s.latency * 0.5, 100.0)
