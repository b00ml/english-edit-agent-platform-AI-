"""配置变更审计写入辅助函数。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import ConfigAuditEvent
from app.versioning import canonical_json


def snapshot_changed(before: Any, after: Any) -> bool:
    """用稳定 JSON 比较快照，避免字典顺序造成伪变更。"""
    return canonical_json(before) != canonical_json(after)


def record_config_change(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    actor_id: str | None,
    tenant_id: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> ConfigAuditEvent | None:
    """将实际配置变化加入当前事务；无变化时不写审计事件。"""
    if not snapshot_changed(before, after):
        return None
    event = ConfigAuditEvent(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_id=actor_id,
        tenant_id=tenant_id,
        before_snapshot=before,
        after_snapshot=after,
    )
    session.add(event)
    return event
