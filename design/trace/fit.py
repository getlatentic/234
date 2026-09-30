# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fits a potrace outline with few nodes: straight runs become lines, the rest become cubic Beziers fitted with
Schneider's algorithm (Graphics Gems I), and nearly axis-aligned edges are snapped to shared coordinates."""

import math
import re

Point = tuple[float, float]
CORNER_DEGREES = 28
LINE_TOLERANCE = 1.6
CURVE_TOLERANCE = 1.4
SNAP_DISTANCE = 3.0
COUNTER_AREA = 6000
COUNTER_TOLERANCE = 5.0


def parse_potrace(text: str, height: float) -> list[dict]:
    """The closed sub-paths of a potrace SVG, y up to y down: {'start': p, 'segs': [('L', p) | ('C', c1, c2, p)]}."""
    data = re.search(r'<path d="([^"]+)"', text).group(1)
    tokens = re.findall(r"[MmCcLlZz]|-?\d+\.?\d*", data)
    paths: list[dict] = []
    current: dict | None = None
    x = y = 0.0
    command = ""
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.isalpha():
            command = token
            i += 1
            if command in "zZ" and current is not None:
                x, y = current["start"]
                paths.append(current)
                current = None
            continue
        n = 6 if command in "cC" else 2
        v = [float(t) for t in tokens[i : i + n]]
        i += n
        rel = command.islower()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if command in "mM":
            x, y = ox + v[0], oy + v[1]
            current = {"start": (x, y), "segs": []}
            command = "l" if rel else "L"
        elif command in "lL":
            x, y = ox + v[0], oy + v[1]
            current["segs"].append(("L", (x, y)))
        else:
            c1, c2, end = (ox + v[0], oy + v[1]), (ox + v[2], oy + v[3]), (ox + v[4], oy + v[5])
            current["segs"].append(("C", c1, c2, end))
            x, y = end
    flip = lambda p: (p[0], height - p[1])  # noqa: E731
    return [
        {"start": flip(p["start"]), "segs": [(s[0], *map(flip, s[1:])) for s in p["segs"]]} for p in paths
    ]


def _bezier(p0: Point, c1: Point, c2: Point, p3: Point, t: float) -> Point:
    u = 1 - t
    return (
        u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p3[0],
        u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p3[1],
    )


def _sample(start: Point, seg: tuple) -> list[Point]:
    if seg[0] == "L":
        return [seg[1]]
    return [_bezier(start, seg[1], seg[2], seg[3], k / 24) for k in range(1, 25)]


def _angle(a: Point, b: Point) -> float:
    return math.degrees(math.atan2(a[0] * b[1] - a[1] * b[0], a[0] * b[0] + a[1] * b[1]))


def _tangent_out(start: Point, seg: tuple) -> Point:
    target = seg[1] if seg[0] == "L" else (seg[1] if seg[1] != start else seg[3])
    return (target[0] - start[0], target[1] - start[1])


def _tangent_in(start: Point, seg: tuple) -> Point:
    end = seg[-1]
    source = start if seg[0] == "L" else (seg[2] if seg[2] != end else start)
    return (end[0] - source[0], end[1] - source[1])


def runs(path: dict) -> list[dict]:
    """The path cut at its corners: each run has its end nodes, its sampled points and its end tangents."""
    starts = [path["start"]] + [s[-1] for s in path["segs"][:-1]]
    segs = path["segs"]
    n = len(segs)
    corner = [
        abs(_angle(_tangent_in(starts[i - 1], segs[i - 1]), _tangent_out(starts[i], segs[i]))) > CORNER_DEGREES
        for i in range(n)
    ]  # corner[i]: the node at the start of segment i
    if sum(corner) < 2:  # a smooth loop, or one corner: split it at the node farthest from the first
        first = corner.index(True) if any(corner) else 0
        corner[first] = True
        far = max(range(n), key=lambda i: math.dist(starts[i], starts[first]))
        corner[far] = True
    first = corner.index(True)
    order = [(first + k) % n for k in range(n)]
    out: list[dict] = []
    cur: list[int] = []
    for idx in order:
        if corner[idx] and cur:
            out.append(_run(cur, starts, segs))
            cur = []
        cur.append(idx)
    out.append(_run(cur, starts, segs))
    return out


def _run(indices: list[int], starts: list[Point], segs: list[tuple]) -> dict:
    points = [starts[indices[0]]]
    for i in indices:
        points += _sample(starts[i], segs[i])
    return {
        "a": starts[indices[0]],
        "b": segs[indices[-1]][-1],
        "points": points,
        "ta": _tangent_out(starts[indices[0]], segs[indices[0]]),
        "tb": _tangent_in(starts[indices[-1]], segs[indices[-1]]),
    }


def _outline(path: dict) -> list[Point]:
    points = [path["start"]]
    for seg in path["segs"]:
        points += _sample(points[-1], seg)
    return points[:-1]


def _area(points: list[Point]) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2


def _simplify(points: list[Point], tolerance: float) -> list[Point]:
    """Douglas-Peucker on a closed outline, cut at its two most distant points."""
    i = 0
    j = max(range(len(points)), key=lambda k: math.dist(points[k], points[i]))
    halves = [points[i : j + 1], points[j:] + points[: i + 1]]

    def reduce(chain: list[Point]) -> list[Point]:
        far = max(range(len(chain)), key=lambda k: _distance_to_line(chain[k], chain[0], chain[-1]))
        if _distance_to_line(chain[far], chain[0], chain[-1]) <= tolerance:
            return [chain[0]]
        return reduce(chain[: far + 1]) + reduce(chain[far:])

    return reduce(halves[0]) + reduce(halves[1])


def _unit(v: Point) -> Point:
    length = math.hypot(*v) or 1.0
    return (v[0] / length, v[1] / length)


def _distance_to_line(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    return abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / length


def _is_straight(points: list[Point]) -> bool:
    return max(_distance_to_line(p, points[0], points[-1]) for p in points) <= LINE_TOLERANCE


def _chord_parameters(points: list[Point]) -> list[float]:
    acc = [0.0]
    for a, b in zip(points, points[1:]):
        acc.append(acc[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    return [v / acc[-1] for v in acc]


def _generate(points: list[Point], params: list[float], ta: Point, tb: Point) -> tuple[Point, Point, Point, Point]:
    p0, p3 = points[0], points[-1]
    c = [[0.0, 0.0], [0.0, 0.0]]
    x = [0.0, 0.0]
    for p, t in zip(points, params):
        u = 1 - t
        b0, b1, b2, b3 = u**3, 3 * u * u * t, 3 * u * t * t, t**3
        a1 = (ta[0] * b1, ta[1] * b1)
        a2 = (tb[0] * b2, tb[1] * b2)
        c[0][0] += a1[0] ** 2 + a1[1] ** 2
        c[0][1] += a1[0] * a2[0] + a1[1] * a2[1]
        c[1][1] += a2[0] ** 2 + a2[1] ** 2
        tmp = (p[0] - (p0[0] * (b0 + b1) + p3[0] * (b2 + b3)), p[1] - (p0[1] * (b0 + b1) + p3[1] * (b2 + b3)))
        x[0] += a1[0] * tmp[0] + a1[1] * tmp[1]
        x[1] += a2[0] * tmp[0] + a2[1] * tmp[1]
    c[1][0] = c[0][1]
    det = c[0][0] * c[1][1] - c[1][0] * c[0][1]
    chord = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
    alpha1 = alpha2 = chord / 3
    if abs(det) > 1e-12:
        a1s = (x[0] * c[1][1] - x[1] * c[0][1]) / det
        a2s = (c[0][0] * x[1] - c[1][0] * x[0]) / det
        if a1s > chord * 0.01 and a2s > chord * 0.01:
            alpha1, alpha2 = a1s, a2s
    return (
        p0,
        (p0[0] + ta[0] * alpha1, p0[1] + ta[1] * alpha1),
        (p3[0] + tb[0] * alpha2, p3[1] + tb[1] * alpha2),
        p3,
    )


def _reparameterise(bez: tuple, points: list[Point], params: list[float]) -> list[float]:
    out = []
    p0, c1, c2, p3 = bez
    for p, t in zip(points, params):
        q = _bezier(*bez, t)
        u = 1 - t
        d1 = tuple(3 * (u * u * (c1[k] - p0[k]) + 2 * u * t * (c2[k] - c1[k]) + t * t * (p3[k] - c2[k])) for k in (0, 1))
        d2 = tuple(6 * (u * (c2[k] - 2 * c1[k] + p0[k]) + t * (p3[k] - 2 * c2[k] + c1[k])) for k in (0, 1))
        num = (q[0] - p[0]) * d1[0] + (q[1] - p[1]) * d1[1]
        den = d1[0] ** 2 + d1[1] ** 2 + (q[0] - p[0]) * d2[0] + (q[1] - p[1]) * d2[1]
        out.append(t if abs(den) < 1e-12 else min(1.0, max(0.0, t - num / den)))
    return out


def _max_error(bez: tuple, points: list[Point], params: list[float]) -> tuple[float, int]:
    worst, at = 0.0, len(points) // 2
    for i, (p, t) in enumerate(zip(points, params)):
        q = _bezier(*bez, t)
        d = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2
        if d > worst:
            worst, at = d, i
    return math.sqrt(worst), at


def fit_cubics(points: list[Point], ta: Point, tb: Point) -> list[tuple]:
    if len(points) < 4:
        chord = math.dist(points[0], points[-1]) / 3
        return [(points[0], (points[0][0] + ta[0] * chord, points[0][1] + ta[1] * chord),
                 (points[-1][0] + tb[0] * chord, points[-1][1] + tb[1] * chord), points[-1])]  # fmt: skip
    params = _chord_parameters(points)
    bez = _generate(points, params, ta, tb)
    error, split = _max_error(bez, points, params)
    for _ in range(12):
        if error <= CURVE_TOLERANCE:
            return [bez]
        params = _reparameterise(bez, points, params)
        bez = _generate(points, params, ta, tb)
        error, split = _max_error(bez, points, params)
    if error <= CURVE_TOLERANCE * 2:
        return [bez]
    split = min(max(split, 1), len(points) - 2)
    centre = _unit((points[split - 1][0] - points[split + 1][0], points[split - 1][1] - points[split + 1][1]))
    return fit_cubics(points[: split + 1], ta, centre) + fit_cubics(points[split:], (-centre[0], -centre[1]), tb)


def fit_path(path: dict) -> list[tuple]:
    """The path as nodes: [('L', a, b) | ('C', a, c1, c2, b)] going round, corner to corner."""
    outline = _outline(path)
    if _area(outline) < COUNTER_AREA:  # a counter such as the A's or the 4's is a polygon
        corners = _simplify(outline, COUNTER_TOLERANCE)
        corners = [c for i, c in enumerate(corners) if _distance_to_line(c, corners[i - 1], corners[(i + 1) % len(corners)]) > 1]
        return [("L", corners[i], corners[(i + 1) % len(corners)]) for i in range(len(corners))]
    out: list[tuple] = []
    for run in runs(path):
        pts = run["points"]
        if _is_straight(pts):
            out.append(("L", run["a"], run["b"]))
            continue
        for p0, c1, c2, p3 in fit_cubics(pts, _unit(run["ta"]), _unit((-run["tb"][0], -run["tb"][1]))):
            out.append(("C", p0, c1, c2, p3))
    return out


def _clusters(values: list[float]) -> dict[float, float]:
    ordered = sorted(set(values))
    groups: list[list[float]] = []
    for v in ordered:
        if groups and v - groups[-1][-1] <= SNAP_DISTANCE:
            groups[-1].append(v)
        else:
            groups.append([v])
    return {v: round(sum(g) / len(g)) for g in groups for v in g}


def snap(paths: list[list[tuple]]) -> list[list[tuple]]:
    """Lines within 2 degrees of an axis become exactly horizontal or vertical on a shared coordinate."""
    lines = [s for p in paths for s in p if s[0] == "L"]
    ys = [v for s in lines if abs(s[1][1] - s[2][1]) <= 2 + abs(s[2][0] - s[1][0]) * 0.035 for v in (s[1][1], s[2][1])]
    xs = [v for s in lines if abs(s[1][0] - s[2][0]) <= 2 + abs(s[2][1] - s[1][1]) * 0.035 for v in (s[1][0], s[2][0])]
    cy, cx = _clusters(ys), _clusters(xs)
    shift: dict[Point, Point] = {}
    for s in lines:
        a, b = s[1], s[2]
        if abs(a[1] - b[1]) <= 2 + abs(b[0] - a[0]) * 0.035:
            y = cy[a[1]]
            for p in (a, b):
                shift[p] = (shift.get(p, p)[0], float(y))
        if abs(a[0] - b[0]) <= 2 + abs(b[1] - a[1]) * 0.035:
            x = cx[a[0]]
            for p in (a, b):
                shift[p] = (float(x), shift.get(p, p)[1])
    moved = lambda p: shift.get(p, (round(p[0]), round(p[1])))  # noqa: E731
    out = []
    for path in paths:
        fixed = []
        for s in path:
            a, b = s[1], s[-1]
            na, nb = moved(a), moved(b)
            if s[0] == "L":
                fixed.append(("L", na, nb))
            else:
                c1 = (s[2][0] + na[0] - a[0], s[2][1] + na[1] - a[1])
                c2 = (s[3][0] + nb[0] - b[0], s[3][1] + nb[1] - b[1])
                fixed.append(("C", na, c1, c2, nb))
        out.append(fixed)
    return out


def to_d(path: list[tuple], origin: Point = (0, 0)) -> str:
    def fmt(p: Point) -> str:
        return f"{round(p[0] - origin[0], 1):g} {round(p[1] - origin[1], 1):g}"

    parts = [f"M{fmt(path[0][1])}"]
    for s in path:
        parts.append(f"L{fmt(s[2])}" if s[0] == "L" else f"C{fmt(s[2])} {fmt(s[3])} {fmt(s[4])}")
    return "".join(parts) + "Z"
