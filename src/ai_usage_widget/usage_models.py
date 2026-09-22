"""Retain observed model identifiers alongside, never instead of, usage totals."""
import re


def model_name(value: object) -> str:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        return value
    return "unknown"


def add_model_usage(bucket: dict, event: dict, fields: tuple[str, ...]) -> None:
    name = model_name(event.get("model"))
    models = bucket.setdefault("_model_usage", {})
    row = models.setdefault(name, {"model": name, **{field: 0 for field in fields}})
    for field in fields:
        row[field] += int(event.get(field) or 0)


def finalize_model_usage(row: dict) -> None:
    models = row.pop("_model_usage", {})
    row["model_breakdowns"] = [models[name].copy() for name in sorted(models)]
