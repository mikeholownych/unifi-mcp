"""Durable policy previews for capability-gated controller QoS."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from unifi_mcp.runtime.client_organization import stable_client_key
from unifi_mcp.runtime.store import RuntimeStore

_SELECTOR_TYPES = {"client", "tag", "group"}


class QoSPlanRepository:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    async def create(
        self,
        *,
        controller: str,
        site: str,
        selector_type: str,
        selector_value: str,
        download_kbps: int,
        upload_kbps: int,
        client_keys: list[str],
        now: datetime | None = None,
    ) -> dict[str, object]:
        if selector_type not in _SELECTOR_TYPES:
            raise ValueError("selector_type must be client, tag, or group")
        if not 1 <= download_kbps <= 100_000_000 or not 1 <= upload_kbps <= 100_000_000:
            raise ValueError("QoS rates must be between 1 and 100000000 kbps")
        targets = sorted(
            {stable_client_key(controller, site, client_key) for client_key in client_keys}
        )
        if not targets:
            raise ValueError("QoS policy target set is empty")
        if len(targets) > 1000:
            raise ValueError("QoS policy plans are limited to 1000 clients")
        if selector_type == "client":
            selector_value = targets[0]
        now = (now or datetime.now(UTC)).astimezone(UTC)
        token = str(uuid4())
        targets_hash = hashlib.sha256(
            json.dumps(targets, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        async with self._store.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO client_qos_plans (
                    token, controller, site, selector_type, selector_value,
                    download_kbps, upload_kbps, targets_hash, status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?)
                """,
                (
                    token,
                    controller,
                    site,
                    selector_type,
                    selector_value,
                    download_kbps,
                    upload_kbps,
                    targets_hash,
                    now.isoformat(),
                    (now + timedelta(hours=1)).isoformat(),
                ),
            )
            await connection.executemany(
                """
                INSERT INTO client_qos_targets (
                    plan_token, client_key, position, status, updated_at
                ) VALUES (?, ?, ?, 'pending', ?)
                """,
                [
                    (token, client_key, position, now.isoformat())
                    for position, client_key in enumerate(targets)
                ],
            )
        result = await self.get(token)
        if result is None:  # pragma: no cover - transaction guarantees this row
            raise RuntimeError("created QoS plan could not be loaded")
        return result

    async def get(self, token: str) -> dict[str, object] | None:
        async with self._store.transaction() as connection:
            plan_cursor = await connection.execute(
                """
                SELECT token, controller, site, selector_type, selector_value,
                       download_kbps, upload_kbps, targets_hash, status, created_at, expires_at
                FROM client_qos_plans WHERE token = ?
                """,
                (token,),
            )
            plan = await plan_cursor.fetchone()
            if plan is None:
                return None
            target_cursor = await connection.execute(
                """
                SELECT client_key, position, status FROM client_qos_targets
                WHERE plan_token = ? ORDER BY position
                """,
                (token,),
            )
            targets = await target_cursor.fetchall()
        return {
            "token": plan[0],
            "controller": plan[1],
            "site": plan[2],
            "selector_type": plan[3],
            "selector_value": plan[4],
            "download_kbps": plan[5],
            "upload_kbps": plan[6],
            "targets_hash": plan[7],
            "status": plan[8],
            "created_at": plan[9],
            "expires_at": plan[10],
            "targets": [
                {"client_key": row[0], "position": row[1], "status": row[2]} for row in targets
            ],
        }

    async def get_for_apply(self, token: str) -> dict[str, object]:
        plan = await self.get(token)
        if plan is None:
            raise ValueError("QoS policy plan does not exist")
        if datetime.fromisoformat(str(plan["expires_at"])).astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("QoS policy plan has expired; create a fresh preview")
        return plan
