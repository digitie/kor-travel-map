"""스트리밍 snapshot의 ``FeatureBundle`` batch를 쓰기 transaction 밖에서 받아 두는 임시 파일.

ADR-113.

:meth:`~kortravelmap.client.AsyncKorTravelMapClient.load_feature_bundle_batches`만 쓴다. stream을
transaction 안에서 당기면 upstream fetch·역지오코딩 내내 전역 ``feature-curation-write`` fence를
쥔다(2026-10-22 실측 2.5시간+). 그래서 stream은 DB session 없이 끝까지 당겨 여기 쌓고, 쓰기
transaction은 그 뒤에 열어 여기서 batch 순서대로 다시 꺼낸다.

메모리는 batch 하나만큼만 쓴다(snapshot 전체를 메모리에 두지 않는 것이 이 경로의 이유다). 직렬화는
``pickle``이다 — 이미 검증된 pydantic 객체를 validator를 다시 돌리지 않고 그대로 되살린다. 파일은
이 프로세스가 방금 쓴 것만 읽는다(외부 입력이 아니다).
"""

from __future__ import annotations

import pickle
from collections.abc import Iterator, Sequence
from tempfile import TemporaryFile
from types import TracebackType
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from kortravelmap.dto import FeatureBundle


class BundleSpool:
    """batch를 순서대로 덧붙이고, 같은 순서로 한 번 이상 다시 읽는다. ``with``로 수명을 묶는다."""

    def __init__(self) -> None:
        self._file: IO[bytes] = TemporaryFile()  # noqa: SIM115 — __exit__가 닫는다
        self.batch_count = 0
        self.bundle_count = 0
        self.byte_count = 0

    def __enter__(self) -> BundleSpool:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._file.close()

    def append(self, batch: Sequence[FeatureBundle]) -> None:
        """빈 batch는 쌓지 않는다(종전 적재 루프도 건너뛰었다)."""
        if not batch:
            return
        self._file.seek(0, 2)
        pickle.dump(tuple(batch), self._file, protocol=pickle.HIGHEST_PROTOCOL)
        self.batch_count += 1
        self.bundle_count += len(batch)
        self.byte_count = self._file.tell()

    def batches(self) -> Iterator[tuple[FeatureBundle, ...]]:
        """쌓은 batch를 처음부터 순서대로 하나씩 되살린다."""
        self._file.seek(0)
        for _ in range(self.batch_count):
            # 이 프로세스가 방금 쓴 파일만 읽는다.
            batch: tuple[FeatureBundle, ...] = pickle.load(self._file)
            yield batch
