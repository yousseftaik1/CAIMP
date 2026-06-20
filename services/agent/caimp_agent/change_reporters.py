"""
CAIMP Agent — change event reporters.

These background tasks watch for changes on the monitored server
and report them to the change-tracker service so the correlation engine
can link them to future anomalies.

Reporters:
  - DockerEventsReporter  — streams `docker events` for container/image changes
  - PackageWatcher        — tails dpkg.log / yum.log for package installs
  - AuthWatcher           — tails auth.log for SSH sessions
  - CronWatcher           — tails syslog for cron executions
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from .config import AgentConfig

log = logging.getLogger("caimp-agent.changes")


class ChangeReporter:
    """Base class — posts a change event to the change-tracker service."""

    def __init__(self, cfg: "AgentConfig", server_id: str, jwt_token: str):
        self.base_url = cfg.platform_url.rstrip("/")
        self.server_id = server_id
        self.jwt_token = jwt_token
        self._http: httpx.AsyncClient | None = None

    async def _post(
        self,
        change_type: str,
        source: str,
        actor: str | None,
        description: str,
        payload: dict,
        image_sha: str | None = None,
    ) -> None:
        if not self._http:
            self._http = httpx.AsyncClient(timeout=10)
        try:
            await self._http.post(
                f"{self.base_url}/api/changes/ingest",
                json={
                    "server_id": self.server_id,
                    "change_type": change_type,
                    "source": source,
                    "actor": actor,
                    "description": description,
                    "payload": payload,
                    "image_sha": image_sha,
                    "occurred_at": datetime.now(tz=timezone.utc).isoformat(),
                },
                headers={"Authorization": f"Bearer {self.jwt_token}"},
            )
            log.debug("Reported change: %s — %s", change_type, description)
        except Exception as exc:
            log.debug("Could not report change event: %s", exc)

    async def run(self) -> None:
        raise NotImplementedError


class DockerEventsReporter(ChangeReporter):
    """Streams `docker events --format json` and reports relevant events."""

    _WATCHED = {"pull", "start", "restart", "stop", "die", "kill"}

    async def run(self) -> None:
        log.info("Docker events reporter starting")
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "events",
                    "--format",
                    "{{json .}}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                if proc.stdout is None:
                    await asyncio.sleep(30)
                    continue

                async for line in proc.stdout:
                    try:
                        evt = json.loads(line.decode().strip())
                    except json.JSONDecodeError:
                        continue

                    action = evt.get("Action", "").lower()
                    etype = evt.get("Type", "").lower()

                    if (
                        etype not in ("container", "image")
                        or action not in self._WATCHED
                    ):
                        continue

                    attrs = evt.get("Actor", {}).get("Attributes", {})
                    image = attrs.get("image") or evt.get("From", "")
                    name = attrs.get("name") or ""
                    sha = attrs.get("imageID") or None

                    change_type = "docker_pull" if action == "pull" else "restart"
                    desc = f"Docker {action}: {name or image}"

                    await self._post(
                        change_type=change_type,
                        source="docker_events",
                        actor="docker",
                        description=desc,
                        payload={"action": action, "image": image, "container": name},
                        image_sha=sha,
                    )

            except FileNotFoundError:
                log.debug(
                    "Docker not available on this server — skipping docker events reporter"
                )
                return
            except Exception as exc:
                log.warning("Docker events reporter error: %s — retrying in 30s", exc)
                await asyncio.sleep(30)


class PackageWatcher(ChangeReporter):
    """Tails dpkg.log and yum.log for package install/remove events."""

    _DPKG_LOG = "/var/log/dpkg.log"
    _YUM_LOG = "/var/log/yum.log"
    _APT_LOG = "/var/log/apt/history.log"

    _INSTALL_RE = re.compile(r"(install|upgrade|remove)\s+(\S+)", re.IGNORECASE)

    async def _tail(self, path: str, source: str) -> None:
        if not os.path.exists(path):
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "tail",
                "-F",
                "-n",
                "0",
                path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            if proc.stdout is None:
                return
            async for line in proc.stdout:
                text = line.decode().strip()
                m = self._INSTALL_RE.search(text)
                if not m:
                    continue
                action = m.group(1).lower()
                package = m.group(2)
                await self._post(
                    change_type="package",
                    source=source,
                    actor="package-manager",
                    description=f"Package {action}: {package}",
                    payload={"action": action, "package": package, "raw": text},
                )
        except Exception as exc:
            log.debug("Package watcher error (%s): %s", path, exc)

    async def run(self) -> None:
        log.info("Package watcher starting")
        await asyncio.gather(
            self._tail(self._DPKG_LOG, "dpkg"),
            self._tail(self._YUM_LOG, "yum"),
            self._tail(self._APT_LOG, "apt"),
        )


class AuthWatcher(ChangeReporter):
    """Tails auth.log for SSH login/logout events."""

    _AUTH_LOG = "/var/log/auth.log"
    _SSH_RE = re.compile(r"sshd.*Accepted\s+\S+\s+for\s+(\S+)\s+from\s+(\S+)")
    _LOGOUT_RE = re.compile(r"sshd.*Disconnected.*user\s+(\S+)")

    async def run(self) -> None:
        if not os.path.exists(self._AUTH_LOG):
            return
        log.info("Auth watcher starting")
        try:
            proc = await asyncio.create_subprocess_exec(
                "tail",
                "-F",
                "-n",
                "0",
                self._AUTH_LOG,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            if proc.stdout is None:
                return
            async for line in proc.stdout:
                text = line.decode().strip()
                m = self._SSH_RE.search(text)
                if m:
                    user, src_ip = m.group(1), m.group(2)
                    await self._post(
                        change_type="ssh_login",
                        source="auth_log",
                        actor=user,
                        description=f"SSH login: {user} from {src_ip}",
                        payload={"user": user, "source_ip": src_ip},
                    )
                    continue
                m = self._LOGOUT_RE.search(text)
                if m:
                    user = m.group(1)
                    await self._post(
                        change_type="ssh_login",
                        source="auth_log",
                        actor=user,
                        description=f"SSH logout: {user}",
                        payload={"user": user, "event": "logout"},
                    )
        except Exception as exc:
            log.debug("Auth watcher error: %s", exc)


class CronWatcher(ChangeReporter):
    """Tails syslog for CRON job executions."""

    _SYSLOG = "/var/log/syslog"
    _CRON_RE = re.compile(r"CRON.*CMD\s+\((.+)\)")

    async def run(self) -> None:
        if not os.path.exists(self._SYSLOG):
            return
        log.info("Cron watcher starting")
        try:
            proc = await asyncio.create_subprocess_exec(
                "tail",
                "-F",
                "-n",
                "0",
                self._SYSLOG,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            if proc.stdout is None:
                return
            async for line in proc.stdout:
                text = line.decode().strip()
                m = self._CRON_RE.search(text)
                if m:
                    cmd = m.group(1)[:120]
                    await self._post(
                        change_type="cron",
                        source="syslog",
                        actor="cron",
                        description=f"Cron job: {cmd}",
                        payload={"command": cmd},
                    )
        except Exception as exc:
            log.debug("Cron watcher error: %s", exc)


async def start_all_reporters(
    cfg: "AgentConfig", server_id: str, jwt_token: str
) -> None:
    """Start all change reporters as background tasks."""
    reporters = [
        DockerEventsReporter(cfg, server_id, jwt_token),
        PackageWatcher(cfg, server_id, jwt_token),
        AuthWatcher(cfg, server_id, jwt_token),
        CronWatcher(cfg, server_id, jwt_token),
    ]
    tasks = [asyncio.create_task(r.run()) for r in reporters]
    log.info("Started %d change reporters", len(tasks))
    # Don't await — these run forever in the background
    return tasks
