import re
import uuid

# fixed forever: every node id in every snapshot derives from this root
_ROOT = uuid.UUID("6f1c2d3e-7a5b-5c4d-9e8f-0a1b2c3d4e5f")
# kinds are graph labels; the label grammar also keeps "kind:key" unambiguous
_LABEL = re.compile(r"[A-Z][A-Za-z]*")


def entity_id(tenant: str, kind: str, natural_key: str) -> uuid.UUID:
    # UUIDv5 makes ingestion idempotent: the same natural key always MERGEs into the same node
    if not _LABEL.fullmatch(kind):
        raise ValueError(f"kind {kind!r} is not a graph label")
    if not natural_key:
        raise ValueError("empty natural key")
    tenant_ns = uuid.uuid5(_ROOT, f"tenant:{tenant}")
    return uuid.uuid5(tenant_ns, f"{kind}:{natural_key}")
