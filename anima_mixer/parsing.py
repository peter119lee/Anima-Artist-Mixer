"""Artist chain parsing: splitting, weights, layer routes, timing routes.

Chain syntax overview (all parts optional, composable):

    wlop                          plain artist, weight 1.0
    ::wlop::1.5                   linear injection weight 1.5
    ::wlop::-0.5                  negative weight = style subtraction
    (wlop:1.1)                    CLIP-side weighting (non-linear), kept verbatim
    ::(wlop:1.1)::0.8             both stacked
    wlop@0-8                      layer route: inject only into DiT blocks 0-8
    wlop%0.0-0.45                 timing route: active only for sampling progress 0.0-0.45
    wlop%0.0-0.45~0.1             timing route with smoothstep fade width 0.1
    ::wlop::1.2@0-8%0.0-0.45~0.1  everything combined
"""

from .constants import WEIGHT_MAX, WEIGHT_MIN


def clamp_float(value, lo, hi):
    return max(lo, min(hi, float(value)))


def _is_timing_suffix_text(text):
    s = str(text or "").strip()
    return bool(s) and all(ch in set("0123456789.-~ ") for ch in s)


def _is_layer_route_segment(text):
    s = str(text or "").strip()
    if not s:
        return False
    if "%" in s:
        s, timing = s.split("%", 1)
        if not _is_timing_suffix_text(timing):
            return False
    return bool(s.strip()) and all(ch in set("0123456789-,， ") for ch in s)


def _comma_continues_layer_route(current_text, next_text):
    cur = str(current_text or "")
    at_idx = cur.rfind("@")
    if at_idx < 0:
        return False
    tail = cur[at_idx + 1:]
    if "%" in tail:
        tail = tail.split("%", 1)[0]
    if not _is_layer_route_segment(tail):
        return False
    return _is_layer_route_segment(next_text)


def split_artist_chain(chain):
    """Split an artist chain. Commas separate artists but may also appear
    inside a trailing @layer route (e.g. ``wlop@0,2,4``)."""
    if not chain:
        return []
    s = str(chain).replace("\r", "\n")
    parts = []
    buf = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\n":
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            i += 1
            continue
        if ch in ",，":
            j = i + 1
            while j < len(s) and s[j] not in ",，\n":
                j += 1
            next_piece = s[i + 1:j]
            if _comma_continues_layer_route("".join(buf), next_piece):
                buf.append(ch)
            else:
                part = "".join(buf).strip()
                if part:
                    parts.append(part)
                buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    part = "".join(buf).strip()
    if part:
        parts.append(part)
    return parts


def parse_artist_weights(parts):
    """Extract ``::name::weight`` linear weights from pre-split chain parts.

    Returns ``(names, weights, has_explicit)``:
      names: list[str] for CLIP encoding (``::weight`` suffix stripped,
             parentheses kept verbatim)
      weights: list[float] linear injection weight per artist (default 1.0)
      has_explicit: True when at least one artist specified ``::weight``

    Invalid (non-numeric) weights fall back to 1.0 without raising.
    Weights are clamped to [WEIGHT_MIN, WEIGHT_MAX]; negative weights
    subtract the artist's style direction instead of adding it.
    """
    names = []
    weights = []
    has_explicit = False
    for raw in parts:
        s = str(raw).strip()
        if not s:
            continue
        weight = 1.0
        explicit = False
        if "::" in s:
            head = s
            if head.startswith("::"):
                head = head[2:]
            if "::" in head:
                name_part, _, w_part = head.rpartition("::")
                w_part = w_part.strip()
                try:
                    w_val = float(w_part)
                    weight = clamp_float(w_val, WEIGHT_MIN, WEIGHT_MAX)
                    explicit = True
                    s = name_part.strip()
                except ValueError:
                    # Unparseable weight: keep the raw text so the user notices.
                    pass
        if not s:
            continue
        names.append(s)
        weights.append(weight)
        if explicit:
            has_explicit = True
    return names, weights, has_explicit


def parse_artist_layer_route(name):
    """Parse a trailing ``@layer_filter`` route from a single artist entry.

    Only the final ``@`` is considered, so artist tags that legitimately
    start with ``@`` (e.g. ``@wlop``) survive untouched.
    """
    s = str(name or "").strip()
    if not s or "@" not in s:
        return s, ""
    base, route = s.rsplit("@", 1)
    route = route.strip()
    if not route:
        return s, ""
    allowed = set("0123456789,- ，")
    if all(ch in allowed for ch in route):
        base = base.strip()
        if base:
            return base, route
    return s, ""


def parse_artist_layer_routes(names):
    clean_names = []
    routes = []
    for name in names:
        clean, route = parse_artist_layer_route(name)
        clean_names.append(clean)
        routes.append(route)
    return clean_names, routes


def parse_artist_timing_route(name):
    """Parse a trailing ``%start-end`` or ``%start-end~fade`` timing route.

    Like layer routes, only the final ``%`` is considered; invalid suffixes
    are kept as plain artist text.
    """
    s = str(name or "").strip()
    if not s or "%" not in s:
        return s, ""
    base, timing = s.rsplit("%", 1)
    timing = timing.strip()
    if not timing:
        return s, ""
    allowed = set("0123456789.-~ ")
    if all(ch in allowed for ch in timing):
        if parse_timing_filter(timing) is None:
            return s, ""
        base = base.strip()
        if base:
            return base, timing
    return s, ""


def parse_artist_timing_routes(names):
    clean_names = []
    timings = []
    for name in names:
        clean, timing = parse_artist_timing_route(name)
        clean_names.append(clean)
        timings.append(timing)
    return clean_names, timings


def parse_layer_filter(text, num_blocks):
    """Parse a layer filter like ``0,3,5-10,-1`` into a sorted block list."""
    if not text:
        return None
    s = str(text).replace("，", ",").replace(" ", "")
    if not s:
        return None
    result = set()
    for part in s.split(","):
        if not part:
            continue
        if "-" in part[1:]:
            dash_idx = part.index("-", 1)
            try:
                lo = int(part[:dash_idx])
                hi = int(part[dash_idx + 1:])
            except ValueError:
                continue
            if lo < 0:
                lo += num_blocks
            if hi < 0:
                hi += num_blocks
            if lo > hi:
                lo, hi = hi, lo
            lo = max(0, lo)
            hi = min(num_blocks - 1, hi)
            if lo <= hi:
                result.update(range(lo, hi + 1))
        else:
            try:
                v = int(part)
            except ValueError:
                continue
            if v < 0:
                v += num_blocks
            if 0 <= v < num_blocks:
                result.add(v)
    return sorted(result) if result else None


def parse_timing_filter(text):
    """Parse ``start-end`` or ``start-end~fade`` into ``(start, end, fade)``.

    All values are sampling-progress percentages in [0, 1]. ``fade`` is the
    smoothstep ramp width applied on both sides of the window (0 = hard
    on/off, the pre-fade behavior). Returns None when unparseable.
    """
    if not text:
        return None
    s = str(text).strip().replace(" ", "")
    if not s:
        return None
    fade = 0.0
    if "~" in s:
        s, fade_text = s.split("~", 1)
        if "~" in fade_text:
            return None
        try:
            fade = float(fade_text)
        except ValueError:
            return None
        if fade < 0.0:
            return None
        fade = clamp_float(fade, 0.0, 0.5)
    if "-" not in s[1:]:
        return None
    dash_idx = s.index("-", 1)
    try:
        start = float(s[:dash_idx])
        end = float(s[dash_idx + 1:])
    except ValueError:
        return None
    if start > end:
        start, end = end, start
    start = clamp_float(start, 0.0, 1.0)
    end = clamp_float(end, 0.0, 1.0)
    if end <= start:
        return None
    return start, end, fade


def normalize_weights(weights):
    total = sum(abs(w) for w in weights)
    if total <= 1e-8:
        return [1.0 / len(weights)] * len(weights)
    return [w / total for w in weights]


def resolve_artist_layer_routes(route_texts, num_blocks):
    routes = []
    has_routes = False
    for route in route_texts or []:
        parsed = parse_layer_filter(route, num_blocks)
        if parsed is not None:
            has_routes = True
            routes.append(set(parsed))
        else:
            routes.append(None)
    return routes, has_routes


def resolve_artist_timing_routes(timing_texts):
    timings = []
    has_timings = False
    for timing in timing_texts or []:
        parsed = parse_timing_filter(timing)
        if parsed is not None:
            has_timings = True
            timings.append(parsed)
        else:
            timings.append(None)
    return timings, has_timings


def resolve_target_blocks_from_options(adv, num_blocks, strict=False):
    layer_filter_text = str((adv or {}).get("layer_filter", "") or "")
    explicit_blocks = parse_layer_filter(layer_filter_text, num_blocks)
    if explicit_blocks is not None:
        return explicit_blocks
    sb = int((adv or {}).get("start_block", 0))
    eb = int((adv or {}).get("end_block", -1))
    sb_real = max(0, sb)
    eb_real = num_blocks - 1 if eb < 0 else min(num_blocks - 1, eb)
    if sb_real > eb_real:
        if strict:
            raise ValueError(
                f"[AnimaCrossAttn] start_block={sb_real} > end_block={eb_real} "
                f"(model has {num_blocks} blocks)"
            )
        return []
    return list(range(sb_real, eb_real + 1))
