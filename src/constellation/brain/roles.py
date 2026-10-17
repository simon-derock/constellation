from pathlib import Path

import yaml


def _role(dept: str) -> str:
    return dept.lower().replace(" ", "_")


def roles_from_config(path: Path) -> dict[str, str]:
    # eval_harness.py ActorVisibilityBuilder._infer_actor_roles; anyone absent is external.
    # Kept free of data libraries: the API runtime imports it, and the free host's memory is shared with the database
    cfg = yaml.safe_load(path.read_text())
    roles = {name: _role(dept) for dept, members in cfg["org_chart"].items() for name in members}
    lifecycle = cfg.get("org_lifecycle") or {}
    for change in (lifecycle.get("scheduled_hires") or []) + (lifecycle.get("scheduled_departures") or []):
        roles[change["name"]] = _role(change["dept"])
    return roles
