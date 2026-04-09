"""Scenario definitions for the SRE Incident Response Environment.

Each scenario defines the services involved, their initial states, the root
causes the agent must discover, and the fixes that resolve them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ServiceDefinition:
    """Defines one microservice inside a scenario."""

    name: str
    status: str = "healthy"  # healthy, degraded, down
    cpu: float = 15.0
    memory: float = 40.0
    latency: float = 50.0
    error_rate: float = 0.1
    connections: int = 120
    dependencies: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    deployment_version: str = "v1.0.0"
    config: Dict[str, str] = field(default_factory=dict)
    is_root_cause: bool = False
    healthcheck_ok: bool = True


@dataclass
class RootCause:
    """A single root cause that the agent must identify and fix."""

    service: str
    description: str
    fix_type: str  # rollback, restart, update_config, scale
    fix_args: Dict[str, Any] = field(default_factory=dict)
    investigation_hints: List[str] = field(default_factory=list)


@dataclass
class Scenario:
    """Full scenario specification."""

    name: str
    difficulty: str  # easy, medium, hard
    max_steps: int
    description: str
    services: Dict[str, ServiceDefinition] = field(default_factory=dict)
    root_causes: List[RootCause] = field(default_factory=list)
    investigation_milestones: List[str] = field(default_factory=list)


# =========================================================================
# EASY: Single service OOM crash
# =========================================================================
_easy_services = {
    "api-gateway": ServiceDefinition(
        name="api-gateway",
        status="degraded",
        cpu=45.0,
        memory=60.0,
        latency=350.0,
        error_rate=12.5,
        connections=890,
        dependencies=["user-service", "order-service", "payment-service"],
        logs=[
            "[2026-04-08T02:14:01Z] WARN  upstream user-service connection refused",
            "[2026-04-08T02:14:03Z] ERROR upstream user-service timeout after 5000ms",
            "[2026-04-08T02:14:05Z] WARN  circuit-breaker OPEN for user-service",
            "[2026-04-08T02:14:10Z] ERROR 502 Bad Gateway - user-service unreachable",
            "[2026-04-08T02:14:15Z] INFO  retrying user-service connection (attempt 3/3)",
            "[2026-04-08T02:14:16Z] ERROR all retries exhausted for user-service",
            "[2026-04-08T02:14:20Z] WARN  request queue depth: 245 (threshold: 100)",
            "[2026-04-08T02:14:25Z] ERROR 504 Gateway Timeout for GET /api/users/profile",
        ],
        deployment_version="v2.3.1",
        config={"timeout": "5000ms", "retries": "3"},
    ),
    "user-service": ServiceDefinition(
        name="user-service",
        status="down",
        cpu=0.0,
        memory=0.0,
        latency=0.0,
        error_rate=100.0,
        connections=0,
        dependencies=["database"],
        logs=[
            "[2026-04-08T02:10:00Z] INFO  deploying user-service v2.5.0-rc1",
            "[2026-04-08T02:10:05Z] INFO  deployment v2.5.0-rc1 started successfully",
            "[2026-04-08T02:10:30Z] WARN  memory usage at 78% (threshold 80%)",
            "[2026-04-08T02:11:00Z] WARN  memory usage at 85% - approaching limit",
            "[2026-04-08T02:11:15Z] ERROR java.lang.OutOfMemoryError: Java heap space",
            "[2026-04-08T02:11:15Z] ERROR   at com.app.cache.UserProfileCache.loadAll(UserProfileCache.java:142)",
            "[2026-04-08T02:11:15Z] ERROR   at com.app.service.UserService.init(UserService.java:67)",
            "[2026-04-08T02:11:16Z] FATAL OutOfMemoryError: container killed by OOM killer (used 2048MB / 2048MB limit)",
            "[2026-04-08T02:11:16Z] INFO  container exited with code 137 (OOMKilled)",
            "[2026-04-08T02:11:17Z] INFO  restart attempt 1/3 failed - OOMKilled",
            "[2026-04-08T02:11:20Z] INFO  restart attempt 2/3 failed - OOMKilled",
            "[2026-04-08T02:11:23Z] INFO  restart attempt 3/3 failed - OOMKilled",
            "[2026-04-08T02:11:25Z] ERROR service user-service entered CrashLoopBackOff",
            "[2026-04-08T02:11:25Z] INFO  last healthy deployment: v2.4.9",
        ],
        deployment_version="v2.5.0-rc1",
        config={"heap_size": "2048m", "cache_preload": "true"},
        is_root_cause=True,
        healthcheck_ok=False,
    ),
    "order-service": ServiceDefinition(
        name="order-service",
        status="healthy",
        cpu=22.0,
        memory=45.0,
        latency=80.0,
        error_rate=0.5,
        connections=200,
        dependencies=["database", "payment-service"],
        logs=[
            "[2026-04-08T02:14:10Z] WARN  user-service lookup failed, using cached data",
            "[2026-04-08T02:14:15Z] INFO  order processing nominal",
        ],
        deployment_version="v3.1.2",
        config={},
    ),
    "payment-service": ServiceDefinition(
        name="payment-service",
        status="healthy",
        cpu=18.0,
        memory=38.0,
        latency=95.0,
        error_rate=0.2,
        connections=150,
        dependencies=["database"],
        logs=[
            "[2026-04-08T02:14:10Z] INFO  payment processing nominal",
            "[2026-04-08T02:14:15Z] INFO  stripe webhook received",
        ],
        deployment_version="v1.8.0",
        config={},
    ),
    "database": ServiceDefinition(
        name="database",
        status="healthy",
        cpu=30.0,
        memory=55.0,
        latency=5.0,
        error_rate=0.0,
        connections=250,
        dependencies=[],
        logs=[
            "[2026-04-08T02:14:00Z] INFO  connection pool: 250/500 active",
            "[2026-04-08T02:14:05Z] INFO  replication lag: 0ms",
        ],
        deployment_version="v14.2",
        config={"max_connections": "500"},
    ),
}

_easy_scenario = Scenario(
    name="service_crash",
    difficulty="easy",
    max_steps=15,
    description=(
        "SEVERITY: P1 - CRITICAL\n"
        "ALERT: user-service is DOWN. Multiple 502/504 errors detected on "
        "api-gateway. User-facing authentication and profile endpoints are "
        "returning errors. Incident started at 02:11 UTC after a deployment "
        "to user-service. Customer impact: ~40% of API requests failing."
    ),
    services=_easy_services,
    root_causes=[
        RootCause(
            service="user-service",
            description="OOM crash after bad deployment v2.5.0-rc1",
            fix_type="rollback",
            fix_args={"service": "user-service"},
            investigation_hints=[
                "check_status('user-service')",
                "read_logs('user-service')",
                "check_metrics('user-service', 'memory')",
            ],
        )
    ],
    investigation_milestones=[
        "list_services",
        "check_status_user-service",
        "read_logs_user-service",
        "rollback_user-service",
    ],
)


# =========================================================================
# MEDIUM: Cascading failure from cache misconfiguration
# =========================================================================
_medium_services = {
    "api-gateway": ServiceDefinition(
        name="api-gateway",
        status="degraded",
        cpu=72.0,
        memory=65.0,
        latency=2500.0,
        error_rate=35.0,
        connections=950,
        dependencies=["user-service", "order-service", "cache-service"],
        logs=[
            "[2026-04-08T03:20:01Z] WARN  response time exceeding SLA (2500ms > 200ms)",
            "[2026-04-08T03:20:05Z] ERROR 504 Gateway Timeout for GET /api/orders",
            "[2026-04-08T03:20:08Z] WARN  thread pool exhausted, queuing requests",
            "[2026-04-08T03:20:10Z] ERROR upstream database connection pool saturated",
            "[2026-04-08T03:20:15Z] WARN  circuit-breaker HALF-OPEN for order-service",
            "[2026-04-08T03:20:20Z] ERROR cascading timeout from order-service",
        ],
        deployment_version="v2.3.1",
        config={"timeout": "3000ms"},
    ),
    "cache-service": ServiceDefinition(
        name="cache-service",
        status="degraded",
        cpu=10.0,
        memory=95.0,
        latency=800.0,
        error_rate=65.0,
        connections=50,
        dependencies=[],
        logs=[
            "[2026-04-08T03:00:00Z] INFO  config reload triggered",
            "[2026-04-08T03:00:01Z] WARN  maxmemory set to 32mb (was 512mb)",
            "[2026-04-08T03:00:02Z] INFO  eviction policy: allkeys-lru",
            "[2026-04-08T03:05:00Z] WARN  maxmemory reached, evicting keys aggressively",
            "[2026-04-08T03:10:00Z] ERROR cache hit ratio dropped to 5% (was 95%)",
            "[2026-04-08T03:10:05Z] WARN  eviction rate: 5000 keys/sec",
            "[2026-04-08T03:15:00Z] ERROR cache effectively useless - all reads are misses",
            "[2026-04-08T03:15:05Z] WARN  all traffic falling through to database",
            "[2026-04-08T03:20:00Z] ERROR maxmemory limit too low: 32mb configured, need 512mb+",
        ],
        deployment_version="v6.2.0",
        config={"maxmemory": "32mb", "eviction_policy": "allkeys-lru"},
        is_root_cause=True,
        healthcheck_ok=True,
    ),
    "user-service": ServiceDefinition(
        name="user-service",
        status="degraded",
        cpu=55.0,
        memory=70.0,
        latency=1800.0,
        error_rate=20.0,
        connections=400,
        dependencies=["database", "cache-service"],
        logs=[
            "[2026-04-08T03:15:01Z] WARN  cache miss for user profile, falling back to DB",
            "[2026-04-08T03:15:05Z] WARN  database query latency: 1500ms (threshold: 200ms)",
            "[2026-04-08T03:15:10Z] ERROR connection pool nearly exhausted (95/100)",
            "[2026-04-08T03:20:00Z] ERROR timeout waiting for database connection",
        ],
        deployment_version="v2.4.9",
        config={"cache_ttl": "300s"},
    ),
    "order-service": ServiceDefinition(
        name="order-service",
        status="degraded",
        cpu=60.0,
        memory=72.0,
        latency=3200.0,
        error_rate=40.0,
        connections=380,
        dependencies=["database", "cache-service", "payment-service"],
        logs=[
            "[2026-04-08T03:15:01Z] WARN  cache miss for order data, querying database",
            "[2026-04-08T03:15:10Z] ERROR database connection timeout after 5000ms",
            "[2026-04-08T03:20:00Z] ERROR order creation failed: database overloaded",
            "[2026-04-08T03:20:05Z] WARN  order queue backing up: 450 pending",
        ],
        deployment_version="v3.1.2",
        config={},
    ),
    "payment-service": ServiceDefinition(
        name="payment-service",
        status="healthy",
        cpu=20.0,
        memory=42.0,
        latency=120.0,
        error_rate=1.0,
        connections=100,
        dependencies=["database"],
        logs=[
            "[2026-04-08T03:20:00Z] WARN  slight latency increase on DB queries",
            "[2026-04-08T03:20:05Z] INFO  payment processing mostly nominal",
        ],
        deployment_version="v1.8.0",
        config={},
    ),
    "database": ServiceDefinition(
        name="database",
        status="degraded",
        cpu=95.0,
        memory=88.0,
        latency=1500.0,
        error_rate=15.0,
        connections=490,
        dependencies=[],
        logs=[
            "[2026-04-08T03:10:00Z] WARN  connection count surging: 350 -> 490 in 10 min",
            "[2026-04-08T03:15:00Z] ERROR connection pool near capacity (490/500)",
            "[2026-04-08T03:15:05Z] WARN  query latency p99: 1500ms (normally 5ms)",
            "[2026-04-08T03:20:00Z] ERROR too many connections, rejecting new requests",
            "[2026-04-08T03:20:05Z] WARN  disk I/O saturated at 98%",
        ],
        deployment_version="v14.2",
        config={"max_connections": "500"},
    ),
}

_medium_scenario = Scenario(
    name="cascading_failure",
    difficulty="medium",
    max_steps=25,
    description=(
        "SEVERITY: P1 - CRITICAL\n"
        "ALERT: Widespread service degradation across the platform. "
        "order-service latency at 3200ms (SLA: 200ms), database CPU at 95%, "
        "cache-service reporting 65% error rate. Multiple services experiencing "
        "timeouts. Started approximately 20 minutes ago. Customer impact: "
        "order processing severely degraded, ~35% of all requests timing out."
    ),
    services=_medium_services,
    root_causes=[
        RootCause(
            service="cache-service",
            description="Cache maxmemory misconfigured to 32mb (should be 512mb), causing near-zero hit rate and all traffic hitting database directly",
            fix_type="update_config",
            fix_args={"service": "cache-service", "key": "maxmemory", "value": "512mb"},
            investigation_hints=[
                "check_status('cache-service')",
                "read_logs('cache-service')",
                "check_metrics('cache-service', 'memory')",
                "check_metrics('database', 'connections')",
            ],
        )
    ],
    investigation_milestones=[
        "list_services",
        "check_status_cache-service",
        "read_logs_cache-service",
        "check_dependencies_cache-service",
        "update_config_cache-service",
        "restart_cache-service",
    ],
)


# =========================================================================
# HARD: Multi-factor degradation (3 independent root causes)
# =========================================================================
_hard_services = {
    "api-gateway": ServiceDefinition(
        name="api-gateway",
        status="degraded",
        cpu=78.0,
        memory=82.0,
        latency=1200.0,
        error_rate=25.0,
        connections=800,
        dependencies=["user-service", "order-service", "auth-service", "payment-service"],
        logs=[
            "[2026-04-08T04:00:00Z] WARN  memory usage climbing: 72% -> 82% in 2 hours",
            "[2026-04-08T04:00:05Z] WARN  verbose logging enabled - disk usage increasing",
            "[2026-04-08T04:05:00Z] ERROR log volume: 50GB/hour (normal: 2GB/hour)",
            "[2026-04-08T04:05:05Z] WARN  /var/log partition at 92% capacity",
            "[2026-04-08T04:10:00Z] ERROR memory leak detected in request logging middleware",
            "[2026-04-08T04:10:05Z] WARN  GC pause times increasing: 200ms -> 800ms",
            "[2026-04-08T04:15:00Z] ERROR log buffer allocation growing unbounded",
            "[2026-04-08T04:15:05Z] WARN  verbose_logging=true set in last config push",
            "[2026-04-08T04:20:00Z] ERROR memory usage 82% and rising, potential OOM in ~30 min",
            "[2026-04-08T04:20:05Z] WARN  auth-service returning SSL errors intermittently",
        ],
        deployment_version="v2.3.1",
        config={"verbose_logging": "true", "log_level": "TRACE"},
        is_root_cause=True,
        healthcheck_ok=True,
    ),
    "auth-service": ServiceDefinition(
        name="auth-service",
        status="degraded",
        cpu=35.0,
        memory=45.0,
        latency=500.0,
        error_rate=30.0,
        connections=300,
        dependencies=["database"],
        logs=[
            "[2026-04-08T04:00:00Z] WARN  SSL certificate expires in 2 hours",
            "[2026-04-08T04:05:00Z] ERROR SSL handshake failed: certificate near expiry, some clients rejecting",
            "[2026-04-08T04:10:00Z] ERROR javax.net.ssl.SSLHandshakeException: certificate will expire at 2026-04-08T06:00:00Z",
            "[2026-04-08T04:10:05Z] WARN  30% of TLS connections failing due to strict certificate validation by clients",
            "[2026-04-08T04:15:00Z] ERROR token validation failing for requests routed through strict-TLS proxy",
            "[2026-04-08T04:15:05Z] INFO  current cert: /certs/server.pem (expires 2026-04-08T06:00:00Z)",
            "[2026-04-08T04:15:10Z] INFO  renewed cert available at /certs/renewed/server.pem (expires 2027-04-08)",
            "[2026-04-08T04:20:00Z] ERROR authentication failures spiking: 30% of requests",
        ],
        deployment_version="v1.5.3",
        config={"ssl_cert_path": "/certs/server.pem", "ssl_strict_mode": "true"},
        is_root_cause=True,
        healthcheck_ok=True,
    ),
    "payment-service": ServiceDefinition(
        name="payment-service",
        status="degraded",
        cpu=65.0,
        memory=70.0,
        latency=2000.0,
        error_rate=18.0,
        connections=250,
        dependencies=["database", "auth-service"],
        logs=[
            "[2026-04-08T04:00:00Z] INFO  deploying payment-service v1.9.0-beta",
            "[2026-04-08T04:00:05Z] INFO  deployment v1.9.0-beta started",
            "[2026-04-08T04:05:00Z] WARN  intermittent race condition in transaction locking",
            "[2026-04-08T04:05:05Z] ERROR deadlock detected in payment_transactions table",
            "[2026-04-08T04:10:00Z] ERROR java.util.ConcurrentModificationException in PaymentProcessor.process()",
            "[2026-04-08T04:10:05Z] ERROR race condition: duplicate charge for order #48291",
            "[2026-04-08T04:15:00Z] WARN  transaction rollback rate: 18% (threshold: 1%)",
            "[2026-04-08T04:15:05Z] ERROR payment reconciliation mismatch: $12,450 discrepancy",
            "[2026-04-08T04:20:00Z] ERROR v1.9.0-beta introduced concurrency bug in new payment pipeline",
            "[2026-04-08T04:20:05Z] INFO  last stable version: v1.8.0",
        ],
        deployment_version="v1.9.0-beta",
        config={"concurrency_level": "10"},
        is_root_cause=True,
        healthcheck_ok=True,
    ),
    "user-service": ServiceDefinition(
        name="user-service",
        status="degraded",
        cpu=40.0,
        memory=55.0,
        latency=600.0,
        error_rate=12.0,
        connections=350,
        dependencies=["database", "auth-service", "cache-service"],
        logs=[
            "[2026-04-08T04:10:00Z] WARN  auth-service returning errors for some requests",
            "[2026-04-08T04:15:00Z] ERROR authentication validation failed for 12% of requests",
            "[2026-04-08T04:20:00Z] WARN  increased latency due to auth retries",
        ],
        deployment_version="v2.4.9",
        config={},
    ),
    "order-service": ServiceDefinition(
        name="order-service",
        status="degraded",
        cpu=50.0,
        memory=60.0,
        latency=1500.0,
        error_rate=22.0,
        connections=280,
        dependencies=["database", "payment-service", "user-service"],
        logs=[
            "[2026-04-08T04:10:00Z] WARN  payment-service latency increasing: 2000ms",
            "[2026-04-08T04:15:00Z] ERROR order completion failing: payment timeout",
            "[2026-04-08T04:15:05Z] ERROR duplicate payment detected for order #48291",
            "[2026-04-08T04:20:00Z] WARN  order failure rate: 22% (threshold: 2%)",
        ],
        deployment_version="v3.1.2",
        config={},
    ),
    "cache-service": ServiceDefinition(
        name="cache-service",
        status="healthy",
        cpu=15.0,
        memory=50.0,
        latency=3.0,
        error_rate=0.1,
        connections=200,
        dependencies=[],
        logs=[
            "[2026-04-08T04:00:00Z] INFO  cache hit ratio: 94%",
            "[2026-04-08T04:20:00Z] INFO  cache operating normally",
        ],
        deployment_version="v6.2.0",
        config={"maxmemory": "512mb"},
    ),
    "database": ServiceDefinition(
        name="database",
        status="degraded",
        cpu=70.0,
        memory=75.0,
        latency=200.0,
        error_rate=5.0,
        connections=400,
        dependencies=[],
        logs=[
            "[2026-04-08T04:05:00Z] WARN  deadlock detected in payment_transactions table",
            "[2026-04-08T04:10:00Z] WARN  lock contention increasing on payment tables",
            "[2026-04-08T04:15:00Z] ERROR transaction abort rate elevated",
            "[2026-04-08T04:20:00Z] WARN  connections elevated but within limits (400/500)",
        ],
        deployment_version="v14.2",
        config={"max_connections": "500"},
    ),
}

_hard_scenario = Scenario(
    name="multi_factor_degradation",
    difficulty="hard",
    max_steps=40,
    description=(
        "SEVERITY: P1 - CRITICAL\n"
        "ALERT: Multiple simultaneous issues detected across the platform.\n"
        "- api-gateway memory usage at 82% and climbing (potential memory leak)\n"
        "- auth-service SSL errors causing 30% authentication failures\n"
        "- payment-service reporting race conditions and duplicate charges\n"
        "- Overall platform error rate: 25%, latency p99: 2000ms\n"
        "Incident started approximately 20 minutes ago. "
        "Customer impact: payment failures, authentication errors, and "
        "increasing latency across all services. Revenue impact estimated "
        "at $50k/hour."
    ),
    services=_hard_services,
    root_causes=[
        RootCause(
            service="api-gateway",
            description="Memory leak caused by verbose logging misconfiguration",
            fix_type="update_config",
            fix_args={
                "service": "api-gateway",
                "key": "verbose_logging",
                "value": "false",
            },
            investigation_hints=[
                "check_status('api-gateway')",
                "read_logs('api-gateway')",
                "check_metrics('api-gateway', 'memory')",
            ],
        ),
        RootCause(
            service="auth-service",
            description="SSL certificate near expiry causing handshake failures",
            fix_type="update_config",
            fix_args={
                "service": "auth-service",
                "key": "ssl_cert_path",
                "value": "/certs/renewed/server.pem",
            },
            investigation_hints=[
                "check_status('auth-service')",
                "read_logs('auth-service')",
            ],
        ),
        RootCause(
            service="payment-service",
            description="Race condition bug in v1.9.0-beta deployment",
            fix_type="rollback",
            fix_args={"service": "payment-service"},
            investigation_hints=[
                "check_status('payment-service')",
                "read_logs('payment-service')",
                "check_metrics('payment-service', 'error_rate')",
            ],
        ),
    ],
    investigation_milestones=[
        "list_services",
        "check_status_api-gateway",
        "read_logs_api-gateway",
        "update_config_api-gateway",
        "restart_api-gateway",
        "check_status_auth-service",
        "read_logs_auth-service",
        "update_config_auth-service",
        "check_status_payment-service",
        "read_logs_payment-service",
        "rollback_payment-service",
    ],
)


# =========================================================================
# Registry
# =========================================================================
SCENARIOS: Dict[str, Scenario] = {
    "service_crash": _easy_scenario,
    "cascading_failure": _medium_scenario,
    "multi_factor_degradation": _hard_scenario,
}
