from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from krtour_map.standard_data.catalog import StandardDatasetSpec, standard_dataset_spec
from krtour_map.standard_data.exceptions import (
    StandardDataConfigError,
    StandardDataHttpError,
    StandardDataParseError,
)


@dataclass(frozen=True, slots=True)
class StandardDataConfig:
    api_key: str | None = None
    timeout: float = 10.0
    service_key_param: str = "serviceKey"

    @classmethod
    def from_env(
        cls,
        *,
        api_key: str | None = None,
        timeout: float | None = None,
        service_key_param: str = "serviceKey",
    ) -> StandardDataConfig:
        return cls(
            api_key=api_key
            or os.getenv("DATAGOKR_API_KEY")
            or os.getenv("DATA_GO_KR_SERVICE_KEY")
            or os.getenv("PUBLIC_DATA_SERVICE_KEY")
            or os.getenv("SERVICE_KEY"),
            timeout=timeout or float(os.getenv("DATA_GO_KR_TIMEOUT", "10")),
            service_key_param=service_key_param,
        )


@dataclass(frozen=True, slots=True)
class StandardDataPage:
    dataset: StandardDatasetSpec
    items: tuple[dict[str, Any], ...]
    total_count: int
    page_no: int
    num_of_rows: int
    raw: Mapping[str, Any] = field(repr=False)
    request_url: str | None = None
    request_params: Mapping[str, Any] = field(default_factory=dict)
    collected_at: datetime | None = None

    @property
    def is_empty(self) -> bool:
        return not self.items

    @property
    def has_next_page(self) -> bool:
        return self.page_no * self.num_of_rows < self.total_count

    @property
    def next_page_no(self) -> int | None:
        return self.page_no + 1 if self.has_next_page else None


class StandardDataClient:
    """Bounded asyncio client for the five data.go.kr standard datasets.

    This is intentionally not a generic public-data gateway. It only knows the
    standard datasets requested for `python-krtour-map` ETL and exposes a
    krheritage-like `aio()` construction shape.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout: float | None = None,
        session: Any | None = None,
        service_key_param: str = "serviceKey",
    ) -> None:
        self.config = StandardDataConfig.from_env(
            api_key=api_key,
            timeout=timeout,
            service_key_param=service_key_param,
        )
        self.session = session
        self.closed = False

    @classmethod
    def aio(cls, **kwargs: Any) -> StandardDataClient:
        return cls(**kwargs)

    async def __aenter__(self) -> StandardDataClient:
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        close = getattr(self.session, "aclose", None)
        if callable(close):
            await _maybe_await(close())
        self.closed = True

    async def fetch_page(
        self,
        dataset_key: str,
        *,
        page_no: int = 1,
        num_of_rows: int = 1000,
        response_type: str = "json",
        **params: Any,
    ) -> StandardDataPage:
        if page_no <= 0:
            raise ValueError("page_no must be greater than 0")
        if num_of_rows <= 0 or num_of_rows > 1000:
            raise ValueError("num_of_rows must be between 1 and 1000")

        spec = standard_dataset_spec(dataset_key)
        query = {
            "pageNo": page_no,
            "numOfRows": num_of_rows,
            "type": response_type,
            **{key: value for key, value in params.items() if value not in (None, "")},
        }
        if self.config.api_key:
            query[self.config.service_key_param] = self.config.api_key
        elif self.session is None:
            raise StandardDataConfigError(
                "DATAGOKR_API_KEY, DATA_GO_KR_SERVICE_KEY, PUBLIC_DATA_SERVICE_KEY, "
                "or SERVICE_KEY is required for live calls"
            )

        raw = await self._get_json(spec.endpoint_url, query)
        items, total_count = _parse_standard_response(raw)
        return StandardDataPage(
            dataset=spec,
            items=tuple(dict(item) for item in items),
            total_count=total_count,
            page_no=page_no,
            num_of_rows=num_of_rows,
            raw=raw,
            request_url=spec.endpoint_url,
            request_params=query,
            collected_at=datetime.now().astimezone(),
        )

    async def iter_pages(
        self,
        dataset_key: str,
        *,
        page_no: int = 1,
        num_of_rows: int = 1000,
        max_pages: int | None = None,
        max_items: int | None = None,
        **params: Any,
    ) -> AsyncIterator[StandardDataPage]:
        fetched = 0
        pages = 0
        current_page = page_no
        while True:
            page = await self.fetch_page(
                dataset_key,
                page_no=current_page,
                num_of_rows=num_of_rows,
                **params,
            )
            if page.is_empty:
                return
            yield page
            pages += 1
            fetched += len(page.items)
            if max_pages is not None and pages >= max_pages:
                return
            if max_items is not None and fetched >= max_items:
                return
            if page.next_page_no is None:
                return
            current_page = page.next_page_no

    async def debug_dataset(
        self,
        dataset_key: str,
        *,
        page_no: int = 1,
        num_of_rows: int = 10,
        **params: Any,
    ) -> dict[str, Any]:
        spec = standard_dataset_spec(dataset_key)
        try:
            page = await self.fetch_page(
                dataset_key,
                page_no=page_no,
                num_of_rows=num_of_rows,
                **params,
            )
            return {
                "ok": True,
                "dataset": _spec_json(spec),
                "request": {
                    "method": "GET",
                    "url": page.request_url,
                    "params": _redact_params(page.request_params),
                },
                "parsed": {
                    "total_count": page.total_count,
                    "page_no": page.page_no,
                    "num_of_rows": page.num_of_rows,
                    "items": page.items,
                },
            }
        except Exception as exc:  # noqa: BLE001 - debug UI must surface provider errors.
            return {
                "ok": False,
                "dataset": _spec_json(spec),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }

    async def _get_json(self, url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.session is not None:
            return await _session_get_json(self.session, url, params=params)
        return await asyncio.to_thread(_urllib_get_json, url, params, self.config.timeout)


async def _session_get_json(
    session: Any,
    url: str,
    *,
    params: Mapping[str, Any],
) -> Mapping[str, Any]:
    get = getattr(session, "aget", None) or getattr(session, "get", None)
    if not callable(get):
        raise TypeError("session must expose get(...) or aget(...)")
    response = await _maybe_await(get(url, params=dict(params)))
    if isinstance(response, Mapping):
        return response
    json_method = getattr(response, "json", None)
    if callable(json_method):
        data = await _maybe_await(json_method())
        if isinstance(data, Mapping):
            return data
    text = getattr(response, "text", None)
    if isinstance(text, str):
        data = _parse_json_or_xml(text)
        if isinstance(data, Mapping):
            return data
    raise StandardDataParseError("session response did not contain JSON object")


def _urllib_get_json(url: str, params: Mapping[str, Any], timeout: float) -> Mapping[str, Any]:
    request_url = f"{url}?{urlencode(params)}"
    request = Request(request_url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - user-provided URL is catalog-bound.
            body = response.read().decode("utf-8")
    except OSError as exc:
        raise StandardDataHttpError(str(exc)) from exc
    data = _parse_json_or_xml(body)
    if not isinstance(data, Mapping):
        raise StandardDataParseError("standard-data response root must be an object")
    return data


def _parse_standard_response(raw: Mapping[str, Any]) -> tuple[tuple[Mapping[str, Any], ...], int]:
    response = raw.get("response")
    header = response.get("header") if isinstance(response, Mapping) else raw.get("header")
    if isinstance(header, Mapping):
        result_code = str(header.get("resultCode") or header.get("result_code") or "00")
        if result_code not in {"00", "0"}:
            message = header.get("resultMsg") or header.get("result_msg") or "data.go.kr error"
            raise StandardDataHttpError(f"{result_code}: {message}")
    body = response.get("body") if isinstance(response, Mapping) else raw.get("body", raw)
    if not isinstance(body, Mapping):
        raise StandardDataParseError("standard-data response body must be an object")
    items_node = body.get("items", ())
    if isinstance(items_node, Mapping):
        if "item" in items_node:
            items_node = items_node["item"]
        else:
            items_node = tuple(items_node.values())
    if isinstance(items_node, Mapping):
        items = (items_node,)
    elif isinstance(items_node, list | tuple):
        items = tuple(item for item in items_node if isinstance(item, Mapping))
    else:
        items = ()
    total_count = _int_or_none(body.get("totalCount")) or len(items)
    return items, total_count


def _parse_json_or_xml(text: str) -> Mapping[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise StandardDataParseError("standard-data response was empty")
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        try:
            root = ElementTree.fromstring(stripped)
        except ElementTree.ParseError as exc:
            raise StandardDataParseError("standard-data response was neither JSON nor XML") from exc
        converted = _xml_element_to_mapping(root)
        return {_strip_xml_namespace(root.tag): converted}
    if not isinstance(data, Mapping):
        raise StandardDataParseError("standard-data JSON response root must be an object")
    return data


def _xml_element_to_mapping(element: ElementTree.Element) -> Any:
    children = list(element)
    if not children:
        return element.text.strip() if element.text else ""
    result: dict[str, Any] = {}
    for child in children:
        key = _strip_xml_namespace(child.tag)
        value = _xml_element_to_mapping(child)
        existing = result.get(key)
        if existing is None:
            result[key] = value
        elif isinstance(existing, list):
            existing.append(value)
        else:
            result[key] = [existing, value]
    return result


def _strip_xml_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _spec_json(spec: StandardDatasetSpec) -> dict[str, Any]:
    return {
        "dataset_key": spec.dataset_key,
        "dataset_id": spec.dataset_id,
        "title": spec.title,
        "endpoint_url": spec.endpoint_url,
        "portal_url": spec.portal_url,
        "feature_kind": spec.feature_kind,
        "source_entity_type": spec.source_entity_type,
        "official_refresh_cycle": spec.official_refresh_cycle,
        "metadata_probe_interval_days": spec.metadata_probe_interval_days,
        "full_scan_interval_days": spec.full_scan_interval_days,
    }


def _redact_params(params: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in params.items():
        if key.lower() in {"servicekey", "service_key", "apikey", "api_key"}:
            redacted[key] = "<REDACTED>"
        else:
            redacted[key] = value
    return redacted
