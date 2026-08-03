"""네트워크 재시도 가능한 command의 정적 멱등성 분류 정본.

새 POST/PUT/PATCH/DELETE operation은 이 registry에 명시적으로 추가해야 한다.
``DOMAIN_LEDGER`` 항목은 인증 actor와 UUID ``Idempotency-Key``를 사용하는 공통
ledger에 결합한다. 나머지 항목은 이미 가진 더 강한 식별 경계나 비재시도 근거를
코드로 고정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "COMMAND_REGISTRY",
    "CommandPolicy",
    "CommandPolicyKind",
    "OperationKey",
    "command_policy",
]

OperationKey = tuple[str, str]


class CommandPolicyKind(StrEnum):
    """OpenAPI write operation의 재시도 계약."""

    DOMAIN_LEDGER = "domain-ledger"
    SPECIALIZED_LEDGER = "specialized-ledger"
    RESOURCE_CONDITIONAL = "resource-conditional"
    NON_RETRYABLE = "non-retryable"
    QUERY = "query"


@dataclass(frozen=True, slots=True)
class CommandPolicy:
    """한 write operation의 멱등성 소유권."""

    kind: CommandPolicyKind
    reason: str
    operation: str | None = None
    success_status: int | None = None
    replay_headers: tuple[str, ...] = ()
    fingerprint_headers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind in {
            CommandPolicyKind.DOMAIN_LEDGER,
            CommandPolicyKind.SPECIALIZED_LEDGER,
        }:
            if self.operation is None:
                raise ValueError(f"{self.kind.value} policy requires operation")
        elif self.operation is not None:
            raise ValueError(f"{self.kind.value} policy must not declare operation")
        if self.kind is CommandPolicyKind.DOMAIN_LEDGER:
            if self.success_status is None:
                raise ValueError("domain-ledger policy requires success_status")
            unsupported = set(self.replay_headers) - {
                "ETag",
                "Location",
                "Retry-After",
            }
            if unsupported:
                raise ValueError(
                    f"unsupported terminal response headers: {sorted(unsupported)}"
                )
            unsupported_fingerprint_headers = set(self.fingerprint_headers) - {
                "If-Match",
                "If-None-Match",
            }
            if unsupported_fingerprint_headers:
                raise ValueError(
                    "unsupported fingerprint headers: "
                    f"{sorted(unsupported_fingerprint_headers)}"
                )
        elif (
            self.success_status is not None
            or self.replay_headers
            or self.fingerprint_headers
        ):
            raise ValueError(
                f"{self.kind.value} policy must not declare terminal response contract"
            )


def _domain(
    operation: str,
    reason: str,
    *,
    success_status: int = 200,
    replay_headers: tuple[str, ...] = (),
    fingerprint_headers: tuple[str, ...] = (),
) -> CommandPolicy:
    return CommandPolicy(
        kind=CommandPolicyKind.DOMAIN_LEDGER,
        operation=operation,
        reason=reason,
        success_status=success_status,
        replay_headers=replay_headers,
        fingerprint_headers=fingerprint_headers,
    )


def _specialized(operation: str, reason: str) -> CommandPolicy:
    return CommandPolicy(
        kind=CommandPolicyKind.SPECIALIZED_LEDGER,
        operation=operation,
        reason=reason,
    )


def _resource(reason: str) -> CommandPolicy:
    return CommandPolicy(kind=CommandPolicyKind.RESOURCE_CONDITIONAL, reason=reason)


def _non_retryable(reason: str) -> CommandPolicy:
    return CommandPolicy(kind=CommandPolicyKind.NON_RETRYABLE, reason=reason)


def _query(reason: str) -> CommandPolicy:
    return CommandPolicy(kind=CommandPolicyKind.QUERY, reason=reason)


_MUTATION_RESULT = "응답 유실 뒤 같은 actor가 terminal 결과를 재생해야 하는 mutation"
_DESTRUCTIVE_RESULT = "파괴적 side effect를 응답 유실 뒤 다시 실행하지 않아야 하는 command"

_COMMAND_REGISTRY: Final[dict[OperationKey, CommandPolicy]] = {
    ("POST", "/v1/admin/auth-events"): _domain(
        "admin.auth-event.create",
        "감사 event append 중복을 actor-scoped terminal 결과로 억제",
    ),
    ("POST", "/v1/admin/backups"): _domain(
        "admin.backup.create",
        _DESTRUCTIVE_RESULT,
    ),
    ("DELETE", "/v1/admin/backups/{backup_id}"): _domain(
        "admin.backup.delete",
        _DESTRUCTIVE_RESULT,
    ),
    ("POST", "/v1/admin/restore/{backup_id}"): _domain(
        "admin.backup.restore",
        _DESTRUCTIVE_RESULT,
    ),
    ("POST", "/v1/admin/restore/{backup_id}/swap"): _domain(
        "admin.backup.swap",
        _DESTRUCTIVE_RESULT,
    ),
    ("POST", "/v1/admin/features"): _domain(
        "admin.feature.create",
        _MUTATION_RESULT,
    ),
    ("PATCH", "/v1/admin/features/{feature_id}"): _domain(
        "admin.feature.patch",
        _MUTATION_RESULT,
        replay_headers=("ETag",),
        fingerprint_headers=("If-Match",),
    ),
    ("DELETE", "/v1/admin/features/{feature_id}"): _domain(
        "admin.feature.delete",
        _MUTATION_RESULT,
        replay_headers=("ETag",),
        fingerprint_headers=("If-Match",),
    ),
    ("POST", "/v1/admin/features/{feature_id}/deactivate"): _domain(
        "admin.feature.deactivate",
        _MUTATION_RESULT,
    ),
    (
        "POST",
        "/v1/admin/features/change-requests/{request_id}/approve",
    ): _domain(
        "admin.feature-change.approve",
        _MUTATION_RESULT,
        replay_headers=("ETag",),
    ),
    (
        "POST",
        "/v1/admin/features/change-requests/{request_id}/reject",
    ): _domain("admin.feature-change.reject", _MUTATION_RESULT),
    ("POST", "/v1/admin/features/curated"): _domain(
        "admin.curated-feature.create",
        _MUTATION_RESULT,
    ),
    (
        "PATCH",
        "/v1/admin/features/curated/{curated_feature_id}",
    ): _domain("admin.curated-feature.patch", _MUTATION_RESULT),
    (
        "DELETE",
        "/v1/admin/features/curated/{curated_feature_id}",
    ): _domain("admin.curated-feature.delete", _MUTATION_RESULT),
    (
        "POST",
        "/v1/admin/features/curated/{curated_feature_id}/select",
    ): _domain("admin.curated-feature.select", _MUTATION_RESULT),
    (
        "POST",
        "/v1/admin/features/curated/{curated_feature_id}/unselect",
    ): _domain("admin.curated-feature.unselect", _MUTATION_RESULT),
    ("POST", "/v1/admin/curated-themes"): _domain(
        "admin.curated-theme.create",
        _MUTATION_RESULT,
    ),
    ("PATCH", "/v1/admin/curated-themes/{theme_id}"): _domain(
        "admin.curated-theme.patch",
        _MUTATION_RESULT,
    ),
    ("POST", "/v1/admin/curated-sources"): _domain(
        "admin.curated-source.create",
        _MUTATION_RESULT,
    ),
    ("PATCH", "/v1/admin/curated-sources/{source_id}"): _domain(
        "admin.curated-source.patch",
        _MUTATION_RESULT,
    ),
    ("POST", "/v1/admin/curated-source-rules"): _domain(
        "admin.curated-source-rule.create",
        _MUTATION_RESULT,
    ),
    (
        "PATCH",
        "/v1/admin/curated-source-rules/{rule_id}",
    ): _domain("admin.curated-source-rule.patch", _MUTATION_RESULT),
    (
        "POST",
        "/v1/admin/curated-source-rules/{rule_id}/apply",
    ): _domain("admin.curated-source-rule.apply", _MUTATION_RESULT),
    ("POST", "/v1/admin/curations/import"): _domain(
        "admin.curation.import",
        _DESTRUCTIVE_RESULT,
    ),
    ("POST", "/v1/admin/curations"): _domain(
        "admin.curation-collection.create",
        _MUTATION_RESULT,
        success_status=201,
    ),
    ("PATCH", "/v1/admin/curations/{collection_id}"): _domain(
        "admin.curation-collection.patch",
        _MUTATION_RESULT,
    ),
    ("DELETE", "/v1/admin/curations/{collection_id}"): _domain(
        "admin.curation-collection.archive",
        _MUTATION_RESULT,
    ),
    ("POST", "/v1/admin/curations/{collection_id}/items"): _domain(
        "admin.curation-item.create",
        _MUTATION_RESULT,
        success_status=201,
    ),
    (
        "PATCH",
        "/v1/admin/curations/{collection_id}/items/{curation_item_id}",
    ): _domain("admin.curation-item.patch", _MUTATION_RESULT),
    (
        "DELETE",
        "/v1/admin/curations/{collection_id}/items/{curation_item_id}",
    ): _domain("admin.curation-item.archive", _MUTATION_RESULT),
    (
        "POST",
        "/v1/admin/curations/quarantine/{collection_id}/reclassify",
    ): _domain("admin.curation-quarantine.reclassify", _MUTATION_RESULT),
    (
        "PATCH",
        "/v1/admin/features/dedup-reviews/{review_id}",
    ): _domain("admin.dedup-review.decide", _MUTATION_RESULT),
    (
        "PATCH",
        "/v1/admin/features/enrichment-reviews/{review_id}",
    ): _domain("admin.enrichment-review.decide", _MUTATION_RESULT),
    ("POST", "/v1/admin/files/rescan"): _domain(
        "admin.managed-file.rescan",
        _MUTATION_RESULT,
    ),
    ("POST", "/v1/admin/files/{file_id}/purge"): _domain(
        "admin.managed-file.purge",
        _DESTRUCTIVE_RESULT,
    ),
    ("PATCH", "/v1/admin/issues/{issue_id}"): _domain(
        "admin.issue.patch",
        _MUTATION_RESULT,
    ),
    ("POST", "/v1/admin/offline-uploads"): _domain(
        "admin.offline-upload.create",
        _DESTRUCTIVE_RESULT,
        success_status=201,
    ),
    ("DELETE", "/v1/admin/offline-uploads/{upload_id}"): _domain(
        "admin.offline-upload.delete",
        _DESTRUCTIVE_RESULT,
    ),
    (
        "POST",
        "/v1/admin/offline-uploads/{upload_id}/validate",
    ): _domain("admin.offline-upload.validate", _DESTRUCTIVE_RESULT),
    (
        "POST",
        "/v1/admin/offline-uploads/{upload_id}/load",
    ): _domain("admin.offline-upload.load", _DESTRUCTIVE_RESULT),
    (
        "POST",
        "/v1/admin/public-api-keys/{public_api_key_id}/revoke",
    ): _domain("admin.public-api-key.revoke", _DESTRUCTIVE_RESULT),
    ("POST", "/v1/admin/public-api-keys"): _non_retryable(
        "key 원문은 최초 응답에서만 노출하며 terminal ledger에 secret을 저장하지 않음"
    ),
    (
        "PUT",
        "/v1/admin/poi-cache-targets/{external_system}/{target_key}",
    ): _resource("복합 자연키 resource replacement와 generation lock이 재시도 경계"),
    (
        "DELETE",
        "/v1/admin/poi-cache-targets/{external_system}/{target_key}",
    ): _resource("If-Match generation precondition이 stale 재시도를 차단"),
    (
        "POST",
        "/v1/admin/cache-target-event-dead-letters/{event_id}/replays",
    ): _domain(
        "admin.cache-target-dead-letter.replay",
        _DESTRUCTIVE_RESULT,
        success_status=202,
        replay_headers=("Location", "Retry-After"),
        fingerprint_headers=("If-Match",),
    ),
    ("POST", "/v1/admin/cache-target-reconciliations"): _domain(
        "admin.cache-target-reconciliation.request",
        _DESTRUCTIVE_RESULT,
        success_status=202,
        replay_headers=("Location", "Retry-After"),
    ),
    ("PUT", "/v1/ops/datasets/refresh-policy"): _resource(
        "provider+dataset resource replacement와 revision precondition이 경계"
    ),
    (
        "POST",
        "/v1/ops/pipeline/executions/import_job/{execution_id}/cancel",
    ): _specialized(
        "pipeline-cancellation.import-job",
        "pipeline cancellation attempt/member/run journal이 terminal 상태를 소유",
    ),
    (
        "POST",
        "/v1/ops/pipeline/executions/update_request/{execution_id}/cancel",
    ): _specialized(
        "pipeline-cancellation.update-request",
        "pipeline cancellation attempt/member/run journal이 terminal 상태를 소유",
    ),
    ("POST", "/v1/ops/pipeline/requests"): _specialized(
        "feature-update.request",
        "ops.feature_update_request_idempotency가 actor/key/body/result를 소유",
    ),
    (
        "PATCH",
        "/v1/ops/pipeline/schedules/{schedule_name}",
    ): _specialized(
        "dagster-schedule.patch",
        "schedule command request/result/claim event ledger가 외부 Dagster mutation을 소유",
    ),
    (
        "POST",
        "/v1/ops/pipeline/schedules/{schedule_name}/commands",
    ): _specialized(
        "dagster-schedule.command",
        "schedule command request/result/claim event ledger가 외부 Dagster mutation을 소유",
    ),
    (
        "POST",
        "/v1/ops/pipeline/schedules/{schedule_name}/claims/{command_id}/resolve",
    ): _specialized(
        "dagster-schedule.claim-resolve",
        "원 command_id의 active claim과 resolution audit가 재실행 경계",
    ),
    (
        "POST",
        "/v1/ops/pipeline/requests/{request_id}/run-now",
    ): _resource("request generation과 active-run 상태 전이가 중복 실행을 차단"),
    ("POST", "/v1/features/batch"): _query(
        "읽기 batch를 URL 길이와 payload 크기 때문에 POST로 표현"
    ),
    ("POST", "/v1/features/weather/batch"): _query(
        "읽기 batch를 URL 길이와 payload 크기 때문에 POST로 표현"
    ),
    (
        "PUT",
        "/v1/service/cache-targets/{external_system}/{target_key}",
    ): _specialized(
        "cache-target.source.apply",
        "source event ledger가 Idempotency-Key/body/result를 소유",
    ),
    (
        "DELETE",
        "/v1/service/cache-targets/{external_system}/{target_key}",
    ): _specialized(
        "cache-target.source.delete",
        "source event ledger와 If-Match가 tombstone 재시도 경계를 소유",
    ),
    ("POST", "/v1/service/refresh-requests"): _specialized(
        "cache-target.refresh-request.create",
        "기존 feature update idempotency ledger가 refresh request를 소유",
    ),
    (
        "POST",
        "/v1/service/cache-target-streams/{external_system}/restore-fences",
    ): _domain(
        "service.cache-target-restore-fence.create",
        _DESTRUCTIVE_RESULT,
        success_status=201,
        replay_headers=("ETag",),
        fingerprint_headers=("If-Match",),
    ),
    ("POST", "/v1/service/cache-target-reconciliations"): _domain(
        "service.cache-target-reconciliation.begin",
        _DESTRUCTIVE_RESULT,
        success_status=201,
        replay_headers=("ETag", "Location", "Retry-After"),
        fingerprint_headers=("If-Match", "If-None-Match"),
    ),
    (
        "POST",
        "/v1/service/cache-target-reconciliations/{request_id}/seals",
    ): _domain(
        "service.cache-target-reconciliation.seal",
        "sealed fixed snapshot 생성과 running phase 전이를 exact replay",
        replay_headers=("ETag",),
        fingerprint_headers=("If-Match",),
    ),
    ("POST", "/v1/service/cache-target-event-claims"): _specialized(
        "cache-target.event.claim",
        "delivery claim ledger가 lease와 idempotent claim replay를 소유",
    ),
    ("POST", "/v1/service/cache-target-event-acks"): _specialized(
        "cache-target.event.ack",
        "delivery claim ACK state가 contiguous cursor 전진을 소유",
    ),
    ("POST", "/v1/service/cache-target-event-nacks"): _specialized(
        "cache-target.event.nack",
        "delivery state가 retry/dead 전이와 poison block을 소유",
    ),
    (
        "POST",
        "/v1/service/cache-target-event-dead-letters/{event_id}/replays",
    ): _domain(
        "service.cache-target-dead-letter.replay",
        _DESTRUCTIVE_RESULT,
        replay_headers=("ETag",),
        fingerprint_headers=("If-Match",),
    ),
    (
        "POST",
        "/v1/service/cache-target-reconciliations/{request_id}/completions",
    ): _domain(
        "service.cache-target-reconciliation.complete",
        "consumer checksum receipt와 terminal resume 결과를 exact replay",
    ),
    ("POST", "/v1/ops/datasets/preview"): _query(
        "provider fixture/live preview를 반환하지만 durable mutation은 없음"
    ),
    ("POST", "/v1/ops/pipeline/requests/preview"): _query(
        "feature update scope 계획만 반환하며 durable mutation은 없음"
    ),
}

COMMAND_REGISTRY: Final = MappingProxyType(_COMMAND_REGISTRY)


def command_policy(method: str, path: str) -> CommandPolicy:
    """등록된 write operation 정책을 반환하고 미등록이면 fail-close한다."""

    key = (method.upper(), path)
    try:
        return COMMAND_REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"unregistered write operation: {key[0]} {key[1]}") from exc
