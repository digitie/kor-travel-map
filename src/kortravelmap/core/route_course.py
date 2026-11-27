"""``kortravelmap.core.route_course`` — 원천 구간(segment)을 등산 코스로 잇는 순수 함수 (ADR-128).

산림청 등산로·KNPS 탐방로 원천은 **코스가 아니라 구간**을 한 행으로 준다(산림청 중앙값
233 m). 이 모듈은 같은 코스로 묶인 구간들의 선을

1. 끝점끼리 허용오차(:data:`DEFAULT_SNAP_TOLERANCE_DEG`, 약 10 m) 안이면 한 점으로 맞추고
   (원천 디지타이징 틈 — 실측 KNPS 194코스 중 68코스가 정확 일치로는 끊긴다),
2. 겹침을 녹여(``unary_union``) 분기 없는 연속 구간을 하나로 잇고(``linemerge``),
3. 분기점에 매달린 50 m 미만 막다른 토막(시설 진입로 등)을 떼어 다시 잇고,
4. 출발 힌트(:func:`assemble_course`의 ``start_near`` / ``start_far_from``)에 맞는 말단을
   **출발점**으로 방향을 맞춘다.

결과 geometry는 **첫 선이 본선이고 그 정점 순서가 곧 진행 방향**이다 — 출발점은 첫 선의
첫 점, 도착점은 첫 선의 마지막 점이다. 저장(``ST_Multi``)은 정점·파트 순서를 보존하므로 읽기
쪽은 geometry에서 출발·도착을 다시 유도한다(별도 좌표 열을 두지 않는다 — 정본 1개).

모양(``shape``):

- ``path`` — 하나의 열린 선.
- ``loop`` — 하나의 닫힌 선(원점 회귀). 출발 = 도착.
- ``network`` — 분기·끊김이 남아 선이 둘 이상. 첫 선은 출발 말단에서 망을 따라 가장 먼
  말단까지의 최단 경로(본선)이고, 나머지 선(샛길·끊긴 조각)이 뒤따른다.

본 모듈은 ADR-002 core 계층이다 — shapely·pyproj·stdlib만 쓴다.
"""

from __future__ import annotations

import heapq
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

from pyproj import Geod
from shapely import STRtree
from shapely import wkt as _wkt
from shapely.errors import GEOSException, ShapelyError
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, unary_union

__all__ = [
    "DEFAULT_SNAP_TOLERANCE_DEG",
    "DEFAULT_SPUR_MAX_M",
    "AssembledCourse",
    "CourseSegmentGeometry",
    "CourseShape",
    "assemble_course",
    "connected_segment_groups",
    "geodesic_length_m",
    "geometry_contradicts_source",
]

DEFAULT_SNAP_TOLERANCE_DEG: Final[float] = 0.0001
"""끝점 맞춤·연결 판정 허용오차(도). 한반도에서 위도 약 11 m, 경도 약 9 m."""

CourseShape = Literal["path", "loop", "network"]

_GEOD: Final[Geod] = Geod(ellps="WGS84")


@dataclass(frozen=True, slots=True)
class CourseSegmentGeometry:
    """코스 조립 입력 구간 1개.

    ``order_key``는 원천 순번(산림청 ``PMNTN_SN`` / KNPS ``일련번호``)과 원천 id로 만든
    전순서다. 같은 입력이면 같은 출력이 나오도록 모든 정렬이 이 키를 쓴다.
    """

    segment_id: str
    order_key: tuple[int, str]
    wkt: str
    source_length_m: float | None = None
    """원천이 적은 구간 거리(m). 있으면 :func:`geometry_contradicts_source` 가드에 쓴다."""


@dataclass(frozen=True, slots=True)
class AssembledCourse:
    """조립된 코스 geometry와 그 파생값."""

    wkt: str
    shape: CourseShape
    start: tuple[float, float]
    """출발점 ``(lon, lat)`` — geometry 첫 선의 첫 점."""
    end: tuple[float, float]
    """도착점 ``(lon, lat)`` — 첫 선(본선)의 마지막 점. ``loop``이면 출발점과 같다."""
    length_m: float
    """그린 선 전체(본선 + 샛길·끊긴 조각)의 WGS84 측지 길이(m) — 원천이 정의한 코스 전체.
    겹친 구간은 한 번만 센다."""
    main_length_m: float
    """본선(출발→도착) 측지 길이(m). ``path``/``loop``이면 ``length_m``과 같다."""
    part_count: int
    excluded_segment_ids: tuple[str, ...] = ()
    """geometry가 원천 거리와 모순돼 선에서 뺀 구간(계보에는 남는다)."""
    start_matches_hint: bool | None = None
    """출발점이 ``start_near`` 후보 중 하나와 맞았는가(``start_near``를 주지 않았으면 ``None``).
    ``False``면 출발 방향을 원천 근거로 정하지 못한 것이다 — 원천 시종점 이름을 붙이지 않는다."""


GEOMETRY_SOURCE_LENGTH_RATIO_MAX: Final[float] = 3.0
GEOMETRY_SOURCE_LENGTH_SLACK_M: Final[float] = 500.0


def geometry_contradicts_source(geometry_length_m: float, source_length_m: float | None) -> bool:
    """구간 geometry 길이가 원천 거리와 모순되는가.

    실측(2026-11 prod): KNPS 탐방로 617구간 중 8구간은 원천 거리 0.4~12 km인데 geometry가
    공원 전체를 지그재그로 훑는 단일 선(9~383 km, 정점 5천~1.8만)이다. 그런 선을 코스에
    넣으면 코스 길이·모양이 통째로 틀어진다. 원천 거리의 3배와 +500 m를 **모두** 넘을 때만
    모순으로 본다 — 짧은 구간의 반올림·디지타이징 오차는 통과한다.
    """
    if source_length_m is None or source_length_m <= 0:
        return False
    return geometry_length_m > max(
        GEOMETRY_SOURCE_LENGTH_RATIO_MAX * source_length_m,
        source_length_m + GEOMETRY_SOURCE_LENGTH_SLACK_M,
    )


def geodesic_length_m(geom: BaseGeometry) -> float:
    """선 geometry의 WGS84 측지 길이(m)."""
    return float(_GEOD.geometry_length(geom))


def _lines_of(wkt_str: str) -> list[LineString]:
    try:
        geom = _wkt.loads(wkt_str)
    except (ShapelyError, GEOSException, TypeError, ValueError):
        return []
    if isinstance(geom, LineString):
        parts = [geom]
    elif isinstance(geom, MultiLineString):
        parts = list(geom.geoms)
    else:
        return []
    return [part for part in parts if not part.is_empty and len(part.coords) >= 2]


class _UnionFind:
    def __init__(self, size: int) -> None:
        self._parent = list(range(size))

    def find(self, item: int) -> int:
        parent = self._parent
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left == root_right:
            return
        # 작은 index를 대표로 — 입력 순서가 같으면 대표도 같다.
        if root_left < root_right:
            self._parent[root_right] = root_left
        else:
            self._parent[root_left] = root_right


def connected_segment_groups(
    segments: Sequence[CourseSegmentGeometry],
    *,
    tolerance_deg: float = DEFAULT_SNAP_TOLERANCE_DEG,
) -> list[list[CourseSegmentGeometry]]:
    """허용오차 안에서 서로 닿는 구간끼리 묶는다(연결 성분).

    geometry가 없거나 읽을 수 없는 구간은 버린다. 성분은 가장 작은 ``order_key``
    순으로, 성분 안의 구간도 ``order_key`` 순으로 돌려준다.
    """
    ordered = sorted(segments, key=lambda segment: segment.order_key)
    geoms: list[BaseGeometry] = []
    kept: list[CourseSegmentGeometry] = []
    for segment in ordered:
        lines = _lines_of(segment.wkt)
        if not lines:
            continue
        geoms.append(lines[0] if len(lines) == 1 else MultiLineString(lines))
        kept.append(segment)
    if not kept:
        return []
    union_find = _UnionFind(len(kept))
    tree = STRtree(geoms)
    left_idx, right_idx = tree.query(geoms, predicate="dwithin", distance=tolerance_deg)
    for left, right in zip(left_idx.tolist(), right_idx.tolist(), strict=True):
        if left != right:
            union_find.union(int(left), int(right))
    groups: dict[int, list[CourseSegmentGeometry]] = {}
    for index, segment in enumerate(kept):
        groups.setdefault(union_find.find(index), []).append(segment)
    return [groups[root] for root in sorted(groups)]


def _snap_endpoints(
    lines: list[LineString], *, tolerance_deg: float
) -> list[LineString]:
    """허용오차 안의 끝점들을 가장 먼저 나온 끝점 하나로 맞춘다."""
    endpoints: list[tuple[float, float]] = []
    for line in lines:
        coords = list(line.coords)
        endpoints.append((coords[0][0], coords[0][1]))
        endpoints.append((coords[-1][0], coords[-1][1]))
    points = [Point(xy) for xy in endpoints]
    union_find = _UnionFind(len(points))
    tree = STRtree(points)
    left_idx, right_idx = tree.query(points, predicate="dwithin", distance=tolerance_deg)
    for left, right in zip(left_idx.tolist(), right_idx.tolist(), strict=True):
        if left != right:
            union_find.union(int(left), int(right))
    snapped: list[LineString] = []
    for index, line in enumerate(lines):
        coords = [(c[0], c[1]) for c in line.coords]
        coords[0] = endpoints[union_find.find(2 * index)]
        coords[-1] = endpoints[union_find.find(2 * index + 1)]
        # 끝점이 한 점으로 맞춰져 길이 0이 된 짧은 조각은 버린다.
        if len(set(coords)) < 2:
            continue
        snapped.append(LineString(coords))
    return snapped


def _insert_vertex(coords: list[tuple[float, float]], point: tuple[float, float]) -> None:
    """``point``가 놓인 선분 자리에 정점으로 끼워 넣는다(이미 정점이면 그대로)."""
    if point in coords:
        return
    target = Point(point)
    best = min(
        range(len(coords) - 1),
        key=lambda i: (LineString([coords[i], coords[i + 1]]).distance(target), i),
    )
    coords.insert(best + 1, point)


def _attach_dangling_endpoints(
    lines: list[LineString], *, tolerance_deg: float
) -> list[LineString]:
    """다른 선 **중간**에 허용오차 안으로 닿는 막다른 끝점을 그 선 위로 옮긴다(T자 이음).

    끝점끼리만 맞추면(``_snap_endpoints``) 갈림길에서 샛길 끝이 본선 한가운데 몇 m 앞에서
    멈춘 경우가 끊긴 채 남는다. 그 끝점을 상대 선의 가장 가까운 점으로 옮기고 그 점을 상대
    선에 정점으로 넣어, 뒤의 ``unary_union``이 그 자리에서 선을 나누게 한다.
    """
    coords_list = [[(c[0], c[1]) for c in line.coords] for line in lines]
    degree: dict[tuple[float, float], int] = {}
    for coords in coords_list:
        for point in (coords[0], coords[-1]):
            degree[point] = degree.get(point, 0) + 1
    tree = STRtree(lines)
    for index, coords in enumerate(coords_list):
        for end in (0, -1):
            point = coords[end]
            if degree.get(point, 0) != 1:
                continue
            probe = Point(point)
            hits = [
                int(hit)
                for hit in tree.query(probe, predicate="dwithin", distance=tolerance_deg).tolist()
                if int(hit) != index
            ]
            if not hits:
                continue
            target_index = min(
                hits, key=lambda hit: (LineString(coords_list[hit]).distance(probe), hit)
            )
            target = LineString(coords_list[target_index])
            nearest = target.interpolate(target.project(probe))
            attached = (nearest.x, nearest.y)
            if attached == point:
                continue
            coords[end] = attached
            degree[point] -= 1
            degree[attached] = degree.get(attached, 0) + 1
            _insert_vertex(coords_list[target_index], attached)
    return [LineString(coords) for coords in coords_list if len(set(coords)) >= 2]


def _endpoint(line: LineString, *, last: bool) -> tuple[float, float]:
    coord = line.coords[-1] if last else line.coords[0]
    return (coord[0], coord[1])


def _prune_spurs(parts: list[LineString], *, spur_max_m: float) -> list[LineString]:
    """분기점에 매달린 짧은 막다른 토막(시설 진입로·디지타이징 잔가지)을 반복해서 뗀다.

    한쪽 끝이 차수 1(막다른 끝)이고 다른 끝이 차수 3 이상(분기점)인 토막 중 측지 길이가
    ``spur_max_m`` 미만인 것만 뗀다. 떼고 나면 분기점이 차수 2가 되어 양옆이 다시 이어질
    수 있으므로 더 뗄 것이 없을 때까지 ``linemerge``와 번갈아 돈다. 원천 구간은 계보에
    그대로 남는다 — 지도에 그리는 코스 선에서만 빠진다.
    """
    current = parts
    while len(current) > 1:
        degree: dict[tuple[float, float], int] = {}
        for part in current:
            for point in (_endpoint(part, last=False), _endpoint(part, last=True)):
                degree[point] = degree.get(point, 0) + 1
        kept: list[LineString] = []
        removed = False
        for part in current:
            head, tail = _endpoint(part, last=False), _endpoint(part, last=True)
            is_spur = (
                (degree[head] == 1 and degree[tail] >= 3)
                or (degree[tail] == 1 and degree[head] >= 3)
            ) and geodesic_length_m(part) < spur_max_m
            if is_spur:
                removed = True
                continue
            kept.append(part)
        if not removed or not kept:
            break
        merged = linemerge(MultiLineString(kept)) if len(kept) > 1 else kept[0]
        current = [merged] if isinstance(merged, LineString) else list(merged.geoms)
    return current


def _reversed(line: LineString) -> LineString:
    return LineString(list(line.coords)[::-1])


@dataclass(frozen=True, slots=True)
class _StartRule:
    """출발 말단 고르기 규칙. 점수(튜플)가 작을수록 출발점에 어울린다.

    - ``near``(순위 있는 후보): 허용오차(``match_tol``) 안에 드는 후보 중 **순위가 가장 높은**
      후보에 맞는 말단이 이긴다. 어느 후보와도 맞지 않으면 후보 전체에서 가장 가까운 말단.
    - ``far``: 이 점에서 가장 먼 말단.
    """

    near: tuple[Point, ...]
    far: Point | None
    match_tol: float

    def score(self, xy: tuple[float, float]) -> tuple[float, float]:
        point = Point(xy)
        if self.far is not None:
            return (0.0, -float(point.distance(self.far)))
        for rank, candidate in enumerate(self.near):
            distance = float(point.distance(candidate))
            if distance <= self.match_tol:
                return (float(rank), distance)
        return (float(len(self.near)), min(float(point.distance(c)) for c in self.near))

    def matched(self, xy: tuple[float, float]) -> bool | None:
        """출발점이 순위 후보 중 하나와 맞았는가. ``near`` 규칙이 아니면 ``None``."""
        if self.far is not None:
            return None
        point = Point(xy)
        return any(float(point.distance(c)) <= self.match_tol for c in self.near)


def _rotate_ring(line: LineString, rule: _StartRule) -> LineString:
    coords = [(c[0], c[1]) for c in list(line.coords)[:-1]]
    best = min(range(len(coords)), key=lambda i: (rule.score(coords[i]), i))
    rotated = coords[best:] + coords[:best]
    return LineString([*rotated, rotated[0]])


def _orient(line: LineString, rule: _StartRule) -> LineString:
    head = rule.score(_endpoint(line, last=False))
    tail = rule.score(_endpoint(line, last=True))
    return _reversed(line) if tail < head else line


DEFAULT_SPUR_MAX_M: Final[float] = 50.0
""":func:`_prune_spurs`가 떼는 막다른 토막의 최대 길이(m)."""


def assemble_course(
    segments: Sequence[CourseSegmentGeometry],
    *,
    start_near: Sequence[tuple[float, float]] | None = None,
    start_far_from: tuple[float, float] | None = None,
    tolerance_deg: float = DEFAULT_SNAP_TOLERANCE_DEG,
    spur_max_m: float = DEFAULT_SPUR_MAX_M,
) -> AssembledCourse | None:
    """구간들을 하나의 방향 있는 코스 geometry로 조립한다. 선이 하나도 없으면 ``None``.

    출발점 규칙(둘 중 하나만 준다):

    - ``start_near`` — **순위 있는** 후보점 목록. 허용오차의 3배 안에 맞는 후보 중 순위가 가장
      높은 후보의 말단에서 출발한다(KNPS: 원천 노드 그래프에서 들어오는 구간이 없는 노드를
      원천 순번 순으로. 지선 토막 끝도 후보가 되지만 지선은 먼저 떼어지므로 남은 말단과 맞는
      다음 후보가 이긴다). 출발점이 후보와 맞았는지는 ``start_matches_hint``에 남는다.
    - ``start_far_from`` — 이 점에서 가장 먼 말단에서 출발한다(산림청: 산 전체 구간망의
      중심 = 정상부 대용점. 들머리는 망의 바깥쪽에 있다 — 추정 규칙, ADR-128).

    둘 다 없으면 가장 작은 ``order_key`` 구간의 첫 점을 후보 하나로 쓴다.
    """
    if start_near is not None and start_far_from is not None:
        raise ValueError("start_near와 start_far_from은 함께 줄 수 없다")
    ordered = sorted(segments, key=lambda segment: segment.order_key)
    lines: list[LineString] = []
    excluded: list[str] = []
    for segment in ordered:
        segment_lines = _lines_of(segment.wkt)
        if not segment_lines:
            continue
        if geometry_contradicts_source(
            geodesic_length_m(MultiLineString(segment_lines)), segment.source_length_m
        ):
            excluded.append(segment.segment_id)
            continue
        lines.extend(segment_lines)
    if not lines:
        return None
    if start_far_from is not None:
        rule = _StartRule(near=(), far=Point(start_far_from), match_tol=3 * tolerance_deg)
        hinted = False
    else:
        hints = list(start_near) if start_near else [_endpoint(lines[0], last=False)]
        rule = _StartRule(
            near=tuple(Point(xy) for xy in hints), far=None, match_tol=3 * tolerance_deg
        )
        hinted = bool(start_near)
    snapped = _attach_dangling_endpoints(
        _snap_endpoints(lines, tolerance_deg=tolerance_deg), tolerance_deg=tolerance_deg
    )
    if not snapped:
        return None
    noded = unary_union(MultiLineString(snapped))
    # 선 하나뿐이면 unary_union이 LineString을 돌려주고 linemerge는 그것을 받지 않는다.
    merged = noded if isinstance(noded, LineString) else linemerge(noded)
    parts = (
        [merged]
        if isinstance(merged, LineString)
        else [
            part
            for part in getattr(merged, "geoms", ())
            if isinstance(part, LineString) and not part.is_empty
        ]
    )
    if not parts:
        return None
    parts = _prune_spurs(parts, spur_max_m=spur_max_m)
    if len(parts) == 1 and parts[0].is_closed and len(parts[0].coords) >= 4:
        main = _rotate_ring(parts[0], rule)
        shape: CourseShape = "loop"
        rest: list[LineString] = []
    elif len(parts) == 1:
        main = _orient(parts[0], rule)
        shape = "path"
        rest = []
    else:
        main, rest = _main_path(parts, rule)
        shape = "network"
    start = _endpoint(main, last=False)
    geometry = main if not rest else MultiLineString([main, *rest])
    return AssembledCourse(
        wkt=geometry.wkt,
        shape=shape,
        start=start,
        end=_endpoint(main, last=True),
        length_m=geodesic_length_m(geometry),
        main_length_m=geodesic_length_m(main),
        part_count=1 + len(rest),
        excluded_segment_ids=tuple(excluded),
        start_matches_hint=rule.matched(start) if hinted else None,
    )


def _main_path(parts: list[LineString], rule: _StartRule) -> tuple[LineString, list[LineString]]:
    """분기·끊김이 남은 구간망에서 본선을 고른다.

    본선 = 출발 말단에서 망을 따라 **가장 먼** 말단까지의 최단 경로. 출발 말단은 차수 1
    노드(없으면 모든 노드) 중 (출발 규칙 순위, 그 노드가 속한 연결 조각의 길이가 긴 순,
    출발 규칙 거리) 순으로 고른다 — 끊긴 작은 조각의 끝이 이기지 않게 한다. 본선에 들지
    않은 선(샛길·끊긴 조각)은 측지 길이 내림차순(같으면 WKT)으로 뒤에 붙는다.
    """
    adjacency: dict[tuple[float, float], list[tuple[tuple[float, float], float, int]]] = {}
    lengths = [geodesic_length_m(part) for part in parts]
    node_ids: dict[tuple[float, float], int] = {}
    for part in parts:
        for node in (_endpoint(part, last=False), _endpoint(part, last=True)):
            node_ids.setdefault(node, len(node_ids))
    union_find = _UnionFind(len(node_ids))
    for index, part in enumerate(parts):
        head, tail = _endpoint(part, last=False), _endpoint(part, last=True)
        adjacency.setdefault(head, []).append((tail, lengths[index], index))
        adjacency.setdefault(tail, []).append((head, lengths[index], index))
        union_find.union(node_ids[head], node_ids[tail])
    component_length: dict[int, float] = {}
    for index, part in enumerate(parts):
        root = union_find.find(node_ids[_endpoint(part, last=False)])
        component_length[root] = component_length.get(root, 0.0) + lengths[index]
    terminals = sorted(node for node, edges in adjacency.items() if len(edges) == 1)
    candidates = terminals or sorted(adjacency)

    def origin_key(node: tuple[float, float]) -> tuple[float, float, float, tuple[float, float]]:
        rank, distance = rule.score(node)
        size = component_length[union_find.find(node_ids[node])]
        return (rank, -size, distance, node)

    origin = min(candidates, key=origin_key)
    distance: dict[tuple[float, float], float] = {origin: 0.0}
    previous: dict[tuple[float, float], tuple[tuple[float, float], int]] = {}
    queue: list[tuple[float, tuple[float, float]]] = [(0.0, origin)]
    while queue:
        dist, node = heapq.heappop(queue)
        if dist > distance[node]:
            continue
        for neighbour, length, index in adjacency[node]:
            candidate = dist + length
            if candidate < distance.get(neighbour, float("inf")):
                distance[neighbour] = candidate
                previous[neighbour] = (node, index)
                heapq.heappush(queue, (candidate, neighbour))

    def rest_key(index: int) -> tuple[float, str]:
        return (-lengths[index], parts[index].wkt)

    reachable_terminals = [node for node in terminals if node in distance and node != origin]
    pool = reachable_terminals or [node for node in distance if node != origin]
    if not pool:
        longest = min(range(len(parts)), key=rest_key)
        main = _orient(parts[longest], rule)
        others = sorted((i for i in range(len(parts)) if i != longest), key=rest_key)
        return main, [parts[i] for i in others]
    destination = max(pool, key=lambda node: (distance[node], node))
    used: set[int] = set()
    coords: list[tuple[float, float]] = [destination]
    node = destination
    while node != origin:
        prior, index = previous[node]
        used.add(index)
        part_coords = [(c[0], c[1]) for c in parts[index].coords]
        if part_coords[0] != node:
            part_coords.reverse()
        coords.extend(part_coords[1:])
        node = prior
    coords.reverse()
    others = sorted((i for i in range(len(parts)) if i not in used), key=rest_key)
    return LineString(coords), [parts[i] for i in others]
