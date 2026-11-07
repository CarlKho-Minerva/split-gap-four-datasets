"""The only way an analysis script may hand numbers, figures and tables to the paper.

An analysis script (papers/<id>/analysis/analysis.py) does:

    from np_pipeline import kit
    cfg = kit.config()                       # the pre-registered design constants (locked with prereg.md)
    raw = kit.data_dir()                     # the fetched, checksummed dataset
    ...
    kit.number("accRandom", 0.934, "pct1", "window-level random split accuracy, mean over participants")
    kit.figure(fig, "fig_central")           # writes paper/fig_central.pdf
    kit.table("tab_main", latex_rows)        # writes paper/tables/tab_main.tex
    kit.save()

kit.save() writes results/results.json (value, format, description of every number), paper/numbers.tex (one
\\newcommand per number and per config constant), results/figures.json (what each figure drew with: the hex colours
of its marks, the colour of every piece of text, labels that collide) and results/manifest.json (sha256 of every file
it wrote, plus the script, config and data hashes). The gates compare the paper against that manifest, so a number
typed by hand or a figure edited after the run is caught, and they run the dataviz palette validator on the colours
figures.json lists (gates.figure_style).

Figure styling (size, fonts, label offsets, display limits) is not the plan. Read it with kit.style(defaults), which
overlays analysis/figure_style.json: config.json is locked with prereg.md and every number in it becomes a macro in
numbers.tex, so restyling there changes numbers.tex; restyling through kit.style() leaves it byte-identical.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path

WS = Path(os.environ.get("NP_WS", Path.cwd()))
_numbers: dict[str, dict] = {}
_files: dict[str, str] = {}
_figures: dict[str, dict] = {}

# Text and chrome colours for print figures (the dataviz skill: text never wears the data colour). Marks carry the
# series colour; every label, value, title, tick and legend entry is INK, a secondary note MUTED; reference lines
# RULE and reference bands BAND. All four are greys, so the palette check never mistakes them for a series.
INK = "#1A1A1A"
MUTED = "#555555"
RULE = "#777777"
BAND = "#EEEEEE"
NEUTRAL_SPREAD = 0.08   # a colour whose R, G and B differ by at most this (0 to 1) is a grey: chrome, not a series
CONTINUOUS_AT = 13      # this many distinct mark colours in one figure is a colour scale, not a categorical palette

FORMATS = {
    "int": lambda v: f"{int(round(v)):,}".replace(",", "{,}"),
    "f1": lambda v: f"{v:.1f}", "f2": lambda v: f"{v:.2f}", "f3": lambda v: f"{v:.3f}",
    "pct0": lambda v: f"{100 * v:.0f}", "pct1": lambda v: f"{100 * v:.1f}", "pct2": lambda v: f"{100 * v:.2f}",
    "pp1": lambda v: f"{100 * v:.1f}",       # a difference of two proportions, in percentage points
    "p": lambda v: ("< 0.001" if v < 0.001 else f"{v:.3f}"),
    "sci": lambda v: f"{v:.2e}",
}


def _camel(name: str) -> str:
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[^A-Za-z0-9]", name) if w)


def config() -> dict:
    return json.loads((WS / "analysis/config.json").read_text())


def data_dir() -> Path:
    return WS / "data/raw"


def style(defaults: dict | None = None) -> dict:
    """Figure styling: `defaults` overlaid with analysis/figure_style.json when it exists. Not locked and never
    written to numbers.tex, so a restyle changes no number (the figure's own sha256 still goes in the manifest)."""
    out = dict(defaults or {})
    p = WS / "analysis/figure_style.json"
    if p.exists():
        extra = json.loads(p.read_text())
        if not isinstance(extra, dict):
            raise ValueError("analysis/figure_style.json must hold one JSON object")
        out.update(extra)
    return out


def number(name: str, value: float, fmt: str, desc: str) -> None:
    if not re.fullmatch(r"[a-z][A-Za-z]*", name):
        raise ValueError(f"macro name must be letters only and start lowercase: {name!r}")
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; use one of {sorted(FORMATS)}")
    v = float(value)
    if math.isnan(v) or math.isinf(v):
        raise ValueError(f"{name} is {v}; a paper number must be finite")
    if name in _numbers:
        raise ValueError(f"{name} reported twice")
    if not desc.strip():
        raise ValueError(f"{name} needs a description (reviewers and Carl read it)")
    _numbers[name] = {"value": v, "fmt": fmt, "text": FORMATS[fmt](v), "desc": desc}


def _record(path: Path) -> None:
    _files[str(path.relative_to(WS))] = hashlib.sha256(path.read_bytes()).hexdigest()


def figure(fig, name: str) -> Path:
    if name in _figures:
        raise ValueError(f"figure {name} written twice")
    out = WS / "paper" / f"{name}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", metadata={"CreationDate": None, "ModDate": None})
    fig.savefig(WS / "results" / f"{name}.png", bbox_inches="tight", dpi=110)
    _record(out)
    _figures[name] = {"file": str(out.relative_to(WS)), **describe_figure(fig)}
    return out


# ---------------------------------------------------------------- what a figure drew with (for the gates)
def _hex(c) -> str | None:
    """'#RRGGBB' for a matplotlib colour, None when it is fully transparent or not a colour (e.g. 'none')."""
    from matplotlib.colors import to_hex, to_rgba
    try:
        r = to_rgba(c)
    except (ValueError, TypeError):
        return None
    return None if r[3] == 0 else to_hex(r[:3]).upper()


def is_neutral(hexc: str) -> bool:
    rgb = [int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return max(rgb) - min(rgb) <= NEUTRAL_SPREAD


def _no_style(v) -> bool:
    return v is None or str(v).lower() in ("none", "", " ")


def _mark_colours(ax) -> list:
    """Every colour the axes' data marks were drawn in (lines, markers, collections, patches), in drawing order."""
    import numpy as np
    out = []
    for ln in ax.lines:
        if not ln.get_visible():
            continue
        if not _no_style(ln.get_linestyle()) and ln.get_linewidth() > 0:
            out.append(ln.get_color())
        if not _no_style(ln.get_marker()):
            out += [ln.get_markerfacecolor(), ln.get_markeredgecolor()]
    for col in ax.collections:
        if col.get_visible():
            lw = np.atleast_1d(col.get_linewidth())
            out += [tuple(x) for x in np.atleast_2d(col.get_facecolor()) if len(x)]
            if lw.size and lw.max() > 0:
                out += [tuple(x) for x in np.atleast_2d(col.get_edgecolor()) if len(x)]
    for p in ax.patches:
        if p.get_visible():
            if p.get_fill():
                out.append(p.get_facecolor())
            if p.get_linewidth() > 0:
                out.append(p.get_edgecolor())
    return out


def _texts(fig) -> list:
    """The text a reader sees: titles, axis labels, in-view tick labels, direct labels, legends, figure text."""
    seen, out = set(), []

    def add(t, role):
        if t is not None and id(t) not in seen and t.get_visible() and t.get_text().strip():
            seen.add(id(t))
            out.append((t, role))
    for ax in fig.axes:
        for t in (ax.title, getattr(ax, "_left_title", None), getattr(ax, "_right_title", None)):
            add(t, "title")
        for axis, i in ((ax.xaxis, 0), (ax.yaxis, 1)):
            add(axis.label, "axis label")
            lo, hi = sorted(axis.get_view_interval())
            pad = 1e-9 * max(1.0, abs(hi - lo))
            for t in axis.get_ticklabels():
                if lo - pad <= t.get_position()[i] <= hi + pad:   # a tick outside the view is never drawn
                    add(t, "tick label")
        for t in ax.texts:
            add(t, "label")
        leg = ax.get_legend()
        if leg is not None:
            for t in leg.get_texts():
                add(t, "legend")
    for t in fig.texts:
        add(t, "label")
    for attr in ("_suptitle", "_supxlabel", "_supylabel"):
        add(getattr(fig, attr, None), "title")
    for leg in getattr(fig, "legends", []):
        for t in leg.get_texts():
            add(t, "legend")
    return out


def _mark_points(fig, step: float = 2.0, cap: int = 200_000):
    """Display coordinates along every drawn line and at every scatter point, one point every `step` pixels, with
    the colour each belongs to; used to see whether a label sits on a mark or a reference line."""
    import numpy as np
    from matplotlib.collections import LineCollection, PathCollection
    arts = []   # (display xy, colour, joined): a line is sampled between its vertices, scatter points are not
    for ax in fig.axes:
        for ln in ax.lines:
            if ln.get_visible():
                joined = not _no_style(ln.get_linestyle()) and ln.get_linewidth() > 0
                arts.append((ln.get_transform().transform(ln.get_xydata()), ln.get_color(), joined))
        for col in ax.collections:
            if not col.get_visible():
                continue
            line = isinstance(col, LineCollection)
            rgba = np.atleast_2d(col.get_edgecolor() if line else col.get_facecolor())
            colour = tuple(rgba[0]) if rgba.size else None
            if line:
                arts += [(col.get_transform().transform(p.vertices), colour, True) for p in col.get_paths()]
            elif isinstance(col, PathCollection) and len(col.get_offsets()):
                arts.append((col.get_offset_transform().transform(np.asarray(col.get_offsets(), float)), colour,
                             False))
    pts, cols, n = [], [], 0
    for xy, colour, joined in arts:
        xy = np.asarray(xy, float).reshape(-1, 2)
        xy = xy[np.isfinite(xy).all(axis=1)]
        if not len(xy):
            continue
        segs = [xy[:1]]
        for a, b in zip(xy[:-1], xy[1:]):
            if joined:
                k = int(min(np.hypot(*(b - a)) / step, 5000)) + 1
                segs.append(np.linspace(a, b, k + 1)[1:])
            else:
                segs.append(b[None, :])
        seg = np.concatenate(segs)
        pts.append(seg)
        cols += [_hex(colour) if colour is not None else None] * len(seg)
        n += len(seg)
        if n >= cap:   # bounded memory on a dense plot; the label check then sees the first `cap` points
            break
    if not pts:
        return np.zeros((0, 2)), []
    return np.concatenate(pts)[:cap], cols[:cap]


def describe_figure(fig) -> dict:
    """What the figure drew with, for the gates (np_pipeline.gates.figure_style):
    surface   the figure background (the validator measures contrast against it)
    series    chromatic colours of data marks, in drawing order: the palette the validator checks
    neutral   greys used for marks (reference lines, bands): chrome, not series
    text      every visible text with its colour and role; text in a chromatic colour breaks the ink rule
    axes      per panel: title, axis labels, whether it holds data, and dual axes (two panels on one spot)
    overlaps  a label that collides with another text, or sits on a drawn line or point (a warning)"""
    import numpy as np
    if not hasattr(fig.canvas, "get_renderer"):   # a canvas that cannot measure text: measure on Agg instead
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        FigureCanvasAgg(fig)
    fig.canvas.draw()   # fresh layout at the figure's own dpi, so tick labels and text positions are final
    renderer = fig.canvas.get_renderer()
    series, neutral, scales = [], [], []
    axes = []
    for ax in fig.axes:
        hexes = [h for h in (_hex(c) for c in _mark_colours(ax)) if h]
        for h in hexes:
            (neutral if is_neutral(h) else series).append(h)
        if ax.images:
            scales += [im.get_cmap().name for im in ax.images]
        axes.append({"title": ax.get_title(), "xlabel": ax.get_xlabel(), "ylabel": ax.get_ylabel(),
                     "has_data": bool(hexes or ax.images),
                     "position": [round(v, 4) for v in ax.get_position().bounds]})
    series = list(dict.fromkeys(series))
    neutral = list(dict.fromkeys(neutral))
    if len(series) >= CONTINUOUS_AT:
        scales.append(f"{len(series)} distinct mark colours")
    dual = []
    for i, a in enumerate(axes):
        for b in axes[i + 1:]:
            if a["has_data"] and b["has_data"] and a["position"] == b["position"]:
                dual.append(f"{a['title'] or a['ylabel'] or 'a panel'} / {b['title'] or b['ylabel'] or 'a panel'}")
    texts = _texts(fig)
    rows, boxes = [], []
    for t, role in texts:
        panel = t.axes.get_title() if getattr(t, "axes", None) is not None else ""
        rows.append({"text": t.get_text().strip()[:60], "colour": _hex(t.get_color()), "role": role,
                     **({"panel": panel} if panel else {})})
        bb = t.get_window_extent(renderer)
        boxes.append((bb.x0, bb.y0, bb.x1, bb.y1))
    overlaps = []
    for i in range(len(boxes)):            # text on text; a few dozen texts, so all pairs is cheap
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            w = min(a[2], b[2]) - max(a[0], b[0])
            h = min(a[3], b[3]) - max(a[1], b[1])
            if w > 1 and h > 1:
                overlaps.append({"a": rows[i]["text"], "b": rows[j]["text"], "what": "text on text",
                                 "panel": rows[i].get("panel", ""), "px": [round(w, 1), round(h, 1)]})
    pts, pcols = _mark_points(fig)
    if len(pts):
        for (t, role), row, (x0, y0, x1, y1) in zip(texts, rows, boxes):
            if role != "label":            # direct labels are the ones placed beside marks
                continue
            inside = (pts[:, 0] > x0 + 1) & (pts[:, 0] < x1 - 1) & (pts[:, 1] > y0 + 1) & (pts[:, 1] < y1 - 1)
            hit = sorted({pcols[k] or "?" for k in np.flatnonzero(inside)})
            if hit:
                overlaps.append({"a": row["text"], "b": "a drawn line or point in " + ", ".join(hit),
                                 "what": "text on a mark", "panel": row.get("panel", "")})
    return {"surface": _hex(fig.get_facecolor()) or "#FFFFFF", "series": series, "neutral": neutral,
            "colour_scales": scales, "text": rows, "axes": axes, "dual_axes": dual, "overlaps": overlaps}


def table(name: str, latex: str) -> Path:
    out = WS / "paper/tables" / f"{name}.tex"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("% GENERATED by the analysis run (np_pipeline.kit.table). Do not edit.\n" + latex)
    _record(out)
    return out


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save() -> None:
    (WS / "results").mkdir(exist_ok=True)
    cfg = config()
    lines = ["% GENERATED by the analysis run (np_pipeline.kit.save). Every number in the paper comes from here.",
             "% Do not edit: the gate compares this file's sha256 with results/manifest.json."]
    for k, v in sorted(cfg.items()):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            txt = f"{v:,}".replace(",", "{,}") if isinstance(v, int) else f"{v:g}"
            lines.append(f"\\newcommand{{\\cfg{_camel(k)}}}{{{txt}}}  % design constant, analysis/config.json")
    for k, d in sorted(_numbers.items()):
        lines.append(f"\\newcommand{{\\{k}}}{{{d['text']}}}  % {d['desc']}")
    nt = WS / "paper/numbers.tex"
    nt.write_text("\n".join(lines) + "\n")
    _record(nt)
    if _figures:
        fj = WS / "results/figures.json"
        fj.write_text(json.dumps({"kit": {"ink": INK, "muted": MUTED, "rule": RULE, "band": BAND},
                                  "figures": _figures}, indent=1) + "\n")
        _record(fj)
    res = WS / "results/results.json"
    res.write_text(json.dumps({"numbers": _numbers, "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, indent=1))
    data_hashes = json.loads((WS / "provenance.json").read_text()).get("files", {})
    manifest = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": sys.version.split()[0],
        "script_sha256": _sha(WS / "analysis/analysis.py"),
        "config_sha256": _sha(WS / "analysis/config.json"),
        "data_sha256": data_hashes,
        "files": dict(sorted(_files.items())),
    }
    (WS / "results/manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"kit.save: {len(_numbers)} numbers, {len(_files)} files")
