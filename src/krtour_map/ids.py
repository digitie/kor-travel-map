from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from krtour_map.enums import FeatureKind
from krtour_map.providers import normalize_provider_name


def canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def make_payload_hash(data: Any, *, length: int = 32) -> str:
    digest = hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()
    return digest[:length]


def normalize_key_part(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def make_feature_id(
    *,
    provider: str,
    source_type: str,
    source_natural_key: str,
    kind: FeatureKind | str,
    category: str,
    legal_dong_code: str | None = None,
    content_hash: str | None = None,
) -> str:
    provider_name = normalize_provider_name(provider)
    kind_value = kind.value if isinstance(kind, FeatureKind) else str(kind)
    region_part = legal_dong_code if legal_dong_code else "global"
    content_part = content_hash or ""
    raw = "|".join(
        [
            provider_name,
            normalize_key_part(source_type),
            normalize_key_part(source_natural_key),
            normalize_key_part(kind_value),
            normalize_key_part(category),
            region_part,
            content_part,
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"f_{region_part}_{kind_value[:1]}_{digest}"


def make_source_record_key(
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    source_entity_id: str,
    raw_payload_hash: str,
) -> str:
    provider_name = normalize_provider_name(provider)
    raw = "|".join(
        [
            provider_name,
            normalize_key_part(dataset_key),
            normalize_key_part(source_entity_type),
            normalize_key_part(source_entity_id),
            raw_payload_hash,
        ]
    )
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"sr_{digest}"
