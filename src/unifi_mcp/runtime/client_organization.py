"""SQLite repository for controller-independent client organization."""

import hashlib
import re
from datetime import UTC, datetime
from uuid import uuid4

from unifi_mcp.runtime.store import RuntimeStore

_TAG = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,63}$")
_MAC = re.compile(r"^[0-9a-f]{12}$")
_STABLE_KEY = re.compile(r"^sha256:[0-9a-f]{64}$")


def normalize_client_key(value: str) -> str:
    compact = value.strip().lower().replace(":", "").replace("-", "")
    if not _MAC.fullmatch(compact):
        raise ValueError("client identity must be a valid MAC address")
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def stable_client_key(controller: str, site: str, identity: str) -> str:
    if _STABLE_KEY.fullmatch(identity):
        return identity
    mac = normalize_client_key(identity)
    digest = hashlib.sha256(f"{controller}\0{site}\0{mac}".encode()).hexdigest()
    return f"sha256:{digest}"


def normalize_tag(value: str) -> str:
    tag = value.strip().lower()
    if not _TAG.fullmatch(tag):
        raise ValueError(
            "tags must be 1-64 lowercase letters, digits, colon, underscore, or hyphen"
        )
    return tag


def normalize_group_name(value: str) -> str:
    name = " ".join(value.split())
    if not 1 <= len(name) <= 64 or any(ord(character) < 32 for character in name):
        raise ValueError("group names must contain 1-64 printable characters")
    return name


class ClientOrganizationRepository:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    async def replace_tags(
        self, *, controller: str, site: str, client_key: str, tags: list[str]
    ) -> dict[str, object]:
        client_key = stable_client_key(controller, site, client_key)
        normalized = sorted({normalize_tag(tag) for tag in tags})
        if len(normalized) > 50:
            raise ValueError("a client may have at most 50 tags")
        now = datetime.now(UTC).isoformat()
        async with self._store.transaction() as connection:
            await connection.execute(
                "DELETE FROM client_tags WHERE controller = ? AND site = ? AND client_key = ?",
                (controller, site, client_key),
            )
            await connection.executemany(
                """
                INSERT INTO client_tags (controller, site, client_key, tag, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [(controller, site, client_key, tag, now) for tag in normalized],
            )
        return await self.get_client(controller=controller, site=site, client_key=client_key)

    async def create_group(self, *, controller: str, site: str, name: str) -> dict[str, object]:
        name = normalize_group_name(name)
        now = datetime.now(UTC).isoformat()
        group_id = str(uuid4())
        async with self._store.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO client_groups (id, controller, site, name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (group_id, controller, site, name, now, now),
            )
        return {"id": group_id, "name": name, "member_count": 0}

    async def delete_group(self, *, controller: str, site: str, name: str) -> bool:
        name = normalize_group_name(name)
        async with self._store.transaction() as connection:
            result = await connection.execute(
                "DELETE FROM client_groups WHERE controller = ? AND site = ? AND name = ?",
                (controller, site, name),
            )
        return bool(result.rowcount)

    async def assign_group(
        self, *, controller: str, site: str, client_key: str, name: str | None
    ) -> dict[str, object]:
        client_key = stable_client_key(controller, site, client_key)
        async with self._store.transaction() as connection:
            await connection.execute(
                """
                DELETE FROM client_group_memberships
                WHERE controller = ? AND site = ? AND client_key = ?
                """,
                (controller, site, client_key),
            )
            if name is not None:
                name = normalize_group_name(name)
                cursor = await connection.execute(
                    "SELECT id FROM client_groups WHERE controller = ? AND site = ? AND name = ?",
                    (controller, site, name),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise ValueError("client group does not exist in this controller/site scope")
                await connection.execute(
                    """
                    INSERT INTO client_group_memberships (
                        controller, site, client_key, group_id, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (controller, site, client_key, row[0], datetime.now(UTC).isoformat()),
                )
        return await self.get_client(controller=controller, site=site, client_key=client_key)

    async def get_client(self, *, controller: str, site: str, client_key: str) -> dict[str, object]:
        client_key = stable_client_key(controller, site, client_key)
        async with self._store.transaction() as connection:
            tags_cursor = await connection.execute(
                """
                SELECT tag FROM client_tags
                WHERE controller = ? AND site = ? AND client_key = ? ORDER BY tag
                """,
                (controller, site, client_key),
            )
            group_cursor = await connection.execute(
                """
                SELECT groups.id, groups.name
                FROM client_group_memberships AS membership
                JOIN client_groups AS groups ON groups.id = membership.group_id
                WHERE membership.controller = ? AND membership.site = ?
                  AND membership.client_key = ?
                """,
                (controller, site, client_key),
            )
            tags = [row[0] for row in await tags_cursor.fetchall()]
            group_row = await group_cursor.fetchone()
        group = {"id": group_row[0], "name": group_row[1]} if group_row else None
        return {
            "controller": controller,
            "site": site,
            "client_key": client_key,
            "tags": tags,
            "group": group,
        }

    async def list_groups(self, *, controller: str, site: str) -> list[dict[str, object]]:
        async with self._store.transaction() as connection:
            cursor = await connection.execute(
                """
                SELECT groups.id, groups.name, COUNT(membership.client_key)
                FROM client_groups AS groups
                LEFT JOIN client_group_memberships AS membership
                  ON membership.controller = groups.controller
                 AND membership.site = groups.site
                 AND membership.group_id = groups.id
                WHERE groups.controller = ? AND groups.site = ?
                GROUP BY groups.id, groups.name ORDER BY groups.name COLLATE NOCASE
                LIMIT 1000
                """,
                (controller, site),
            )
            rows = await cursor.fetchall()
        return [{"id": row[0], "name": row[1], "member_count": row[2]} for row in rows]

    async def list_client_keys(
        self, *, controller: str, site: str, tag: str | None = None, group: str | None = None
    ) -> list[str]:
        if (tag is None) == (group is None):
            raise ValueError("provide exactly one tag or group")
        if tag is not None:
            sql = """
                SELECT client_key FROM client_tags
                WHERE controller = ? AND site = ? AND tag = ? ORDER BY client_key LIMIT 1000
            """
            parameters = (controller, site, normalize_tag(tag))
        else:
            sql = """
                SELECT membership.client_key
                FROM client_group_memberships AS membership
                JOIN client_groups AS groups ON groups.id = membership.group_id
                WHERE membership.controller = ? AND membership.site = ? AND groups.name = ?
                ORDER BY membership.client_key LIMIT 1000
            """
            parameters = (controller, site, normalize_group_name(group or ""))
        async with self._store.transaction() as connection:
            cursor = await connection.execute(sql, parameters)
            rows = await cursor.fetchall()
        return [row[0] for row in rows]
