"""Generate synthetic IT support tickets using the Claude API.

Generates a configurable number of realistic IT support tickets across all
six ticket categories, balanced by default.  Output is written to CSV for
subsequent ingestion via ``scripts/load_kaggle_data.py``.

NOTE: This script is prepared but NOT executed in Phase 1.
      Run it when Anthropic API usage quota allows.

Usage::

    # From the backend/ directory
    python -m scripts.generate_synthetic_data \\
        --count 1000 \\
        --output data/raw/synthetic_tickets.csv

Environment:
    ANTHROPIC_API_KEY: Required.
    CLAUDE_MODEL: Optional (defaults to claude-haiku-4-5-20251001).
"""

import asyncio
import csv
import json
import time
from pathlib import Path

import anthropic
import typer

from src.core.config import get_settings
from src.core.logging import get_logger
from src.db.models import TicketCategory

logger = get_logger(__name__)
app = typer.Typer(add_completion=False)

# Example IT scenarios per category — used to steer generation prompts
CATEGORY_SCENARIOS: dict[TicketCategory, str] = {
    TicketCategory.INFRASTRUCTURE: (
        "server crashes, VM failures, CPU/memory overload, OS boot failures, "
        "disk I/O errors, RAID degradation, bare-metal provisioning issues"
    ),
    TicketCategory.APPLICATION: (
        "application crashes, slow API responses, deployment failures, "
        "dependency conflicts, memory leaks, feature not working as expected"
    ),
    TicketCategory.SECURITY: (
        "unauthorized login attempts, malware detections, SSL/TLS certificate errors, "
        "firewall misconfiguration, security policy violations, phishing incidents"
    ),
    TicketCategory.DATABASE: (
        "query timeouts, connection pool exhaustion, index corruption, "
        "replication lag, disk space full, backup failures, deadlocks"
    ),
    TicketCategory.ACCESS_MANAGEMENT: (
        "password resets, account lockouts, permission denied errors, "
        "VPN access requests, MFA setup failures, role assignment issues"
    ),
    TicketCategory.NETWORK: (
        "network connectivity drops, packet loss, DNS resolution failures, "
        "bandwidth saturation, VLAN misconfiguration, switch port issues"
    ),
}

TEST_CATEGORY_SCENARIOS: dict[TicketCategory, str] = {
    TicketCategory.INFRASTRUCTURE: (
        "NTP clock drift causing Kerberos auth failures, kernel OOM killer terminating critical services, "
        "iSCSI target unexpected disconnects, hypervisor live-migration failures mid-operation, "
        "firmware update bricking network interface cards, NUMA imbalance causing latency spikes"
    ),
    TicketCategory.APPLICATION: (
        "OAuth token silently expiring mid-session without refresh, race condition under high concurrency load, "
        "silent data corruption in CSV/Excel export functions, third-party webhook delivery timeouts, "
        "locale and encoding bugs breaking international user deployments, feature flag misconfiguration "
        "enabling unfinished functionality in production"
    ),
    TicketCategory.SECURITY: (
        "lateral movement indicators detected across multiple hosts in SIEM, shadow IT SaaS tools "
        "bypassing DLP controls, expired internal root CA causing cascading service trust failures, "
        "unexplained gaps in audit log continuity, insider threat indicators from privileged account "
        "accessing unusual data volumes after hours"
    ),
    TicketCategory.DATABASE: (
        "autovacuum not running on heavily bloated PostgreSQL tables, logical replication slot holding WAL "
        "indefinitely causing disk exhaustion, stale table statistics causing catastrophic query plan changes, "
        "max_connections exhausted by idle client connections, foreign key constraint violation on bulk import "
        "with no clear offending row"
    ),
    TicketCategory.ACCESS_MANAGEMENT: (
        "hardcoded service account credentials found embedded in CI/CD pipeline scripts, orphaned active "
        "accounts belonging to departed employees, conflicting group policy objects preventing domain login, "
        "PAM module misconfiguration locking out all sudo access, conditional access policy blocking "
        "legitimate remote workers after office IP range change"
    ),
    TicketCategory.NETWORK: (
        "asymmetric routing causing intermittent TCP session resets, silent packet loss from MTU mismatch "
        "between segments with ICMP blocked, BGP route flapping destabilising upstream peering, rogue DHCP "
        "server issuing conflicting leases, spanning-tree loop detection shutting down legitimate trunk ports"
    ),
}

SYSTEM_PROMPT = """You are an enterprise IT helpdesk specialist generating realistic support tickets.
Each ticket must be specific, technically accurate, and representative of real enterprise issues.

For each ticket provide:
- title: Concise subject line (10-100 characters)
- description: Detailed problem description (80-200 words), including symptoms, affected systems, error messages where relevant, and business impact
- resolution: Step-by-step remediation (60-150 words), actionable and complete
- priority: Integer 1-5 (1=Critical outage, 2=High, 3=Medium, 4=Low, 5=Informational)

Return ONLY a valid JSON array. No markdown, no explanation."""


@app.command()
def main(
    count: int = typer.Option(1000, "--count", "-n", help="Total tickets to generate"),
    output: Path = typer.Option(
        "data/raw/synthetic_tickets.csv",
        "--output",
        "-o",
        help="Output CSV path",
    ),
    batch_size: int = typer.Option(10, "--batch-size", help="Tickets per API call"),
    rate_limit_rps: float = typer.Option(1.0, "--rps", help="Max API calls per second"),
    categories: str = typer.Option(
        "",
        "--categories",
        help="Comma-separated category values to generate (default: all). "
             "e.g. security,database,network",
    ),
    mode: str = typer.Option(
        "train",
        "--mode",
        help="'train' uses standard scenarios; 'test' uses harder held-out scenarios and omits resolution column.",
    ),
) -> None:
    """Generate synthetic IT support tickets using the Claude API."""
    if mode not in ("train", "test"):
        raise typer.BadParameter("--mode must be 'train' or 'test'")
    category_filter = [c.strip() for c in categories.split(",") if c.strip()] if categories else []
    asyncio.run(_generate(count, output, batch_size, rate_limit_rps, category_filter, mode))


async def _generate(
    count: int,
    output: Path,
    batch_size: int,
    rate_limit_rps: float,
    category_filter: list[str] | None = None,
    mode: str = "train",
) -> None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY must be set to run synthetic data generation. "
            "Set it in .env or the process environment."
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    scenarios = TEST_CATEGORY_SCENARIOS if mode == "test" else CATEGORY_SCENARIOS
    all_categories = list(TicketCategory)
    if category_filter:
        valid = {c.value for c in all_categories}
        unknown = [c for c in category_filter if c not in valid]
        if unknown:
            raise ValueError(f"Unknown categories: {unknown}. Valid: {sorted(valid)}")
        categories = [c for c in all_categories if c.value in category_filter]
    else:
        categories = all_categories
    per_category = count // len(categories)
    output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = (
        ["title", "description", "category", "priority"]
        if mode == "test"
        else ["title", "description", "category", "resolution", "priority"]
    )

    with open(output, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for category in categories:
            logger.info(
                f"Generating tickets for category",
                extra={"metadata": {"category": category.value, "count": per_category, "mode": mode}},
            )
            generated = 0

            while generated < per_category:
                batch_count = min(batch_size, per_category - generated)
                prompt = (
                    f"Generate {batch_count} realistic enterprise IT support tickets "
                    f"about: {scenarios[category]}.\n"
                    f"Return a JSON array of {batch_count} objects."
                )

                try:
                    response = client.messages.create(
                        model=settings.claude_model,
                        max_tokens=4096,
                        system=SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    raw_text = response.content[0].text.strip()

                    # Strip markdown fences if the model wraps the JSON
                    if raw_text.startswith("```"):
                        raw_text = raw_text.split("```")[1]
                        if raw_text.startswith("json"):
                            raw_text = raw_text[4:]

                    tickets = json.loads(raw_text)
                    if not isinstance(tickets, list):
                        tickets = [tickets]

                    for t in tickets:
                        row = {
                            "title": str(t.get("title", "")).strip(),
                            "description": str(t.get("description", "")).strip(),
                            "category": category.value,
                            "priority": int(t.get("priority", 3)),
                        }
                        if mode != "test":
                            row["resolution"] = str(t.get("resolution", "")).strip()
                        writer.writerow(row)
                    generated += len(tickets)
                    logger.info(
                        "Batch generated",
                        extra={"metadata": {
                            "category": category.value,
                            "generated": generated,
                            "target": per_category,
                        }},
                    )

                except json.JSONDecodeError as exc:
                    logger.warning(
                        "JSON parse error — retrying",
                        extra={"metadata": {"error": str(exc)}},
                    )
                except Exception as exc:
                    logger.error(
                        "API call failed — retrying",
                        extra={"metadata": {"error": str(exc)}},
                    )
                    time.sleep(5)
                    continue

                time.sleep(1.0 / rate_limit_rps)

    logger.info(
        "Synthetic data generation complete",
        extra={"metadata": {"output": str(output), "requested_count": count}},
    )


if __name__ == "__main__":
    app()
