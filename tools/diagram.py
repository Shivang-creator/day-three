"""tools/diagram.py (T-25). Renders docs/architecture.png — the architecture
diagram the event requires as a file upload — at exactly 2400 x 1500 px using
matplotlib only (no graphviz / `dot` on this machine, none in the container).

What it draws (PLAN §2, §3, §4.9, §4.10, §11):
  * the DECISION PATH as one horizontal band: nurse's browser -> Cloud Run
    FastAPI -> app/orchestrator.py (the only writer) <-> core/ (pure) ->
    store/ (append-only event log) -> Firestore;
  * the pure core/ box (clock, ladder, gate, routing, sweep) fed from below
    by rules/postnatal.v1.json, which is itself fed by the verbatim citations;
  * the model layer (agent/: reader + writer, google-genai + ADK) OUTSIDE the
    decision path, inside a red dashed "no write tool" boundary, with the
    Quiet Mode switch between it and the orchestrator and a single red arrow
    back down labelled "prose + SymptomForm only — no write tool";
  * the simulated outbox, and a legend of the four epistemic tag pills.

Everything that can drift is read at render time, never hard-coded: the rule
pack version and sign/rule counts come from rules/postnatal.v1.json; the model
string, store and MODEL_OFF come from the environment (.env.local is loaded
only for those three names — the API key is never read, printed or drawn).
Re-run `make diagram` after any route or layer change to regenerate.

Colours are the light tokens from docs/DESIGN.md §2 (the PNG has no dark
mode; it is printed on white for the Devpost gallery). Every piece of text is
>= MIN_PX pixels tall at full size (DESIGN.md floor; checked by
tests/test_diagram.py). Fonts are matplotlib's bundled DejaVu family so the
output is byte-stable across machines. No emblems, no emoji, no Devanagari
(matplotlib's Agg backend cannot shape matras correctly — the UI renders Hindi,
the poster does not).

Run: `python tools/diagram.py [--out path.png]`  (default docs/architecture.png)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import patheffects  # noqa: E402
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "docs" / "architecture.png"
PACK_PATH = ROOT / "rules" / "postnatal.v1.json"

# ---------------------------------------------------------------- geometry --
WIDTH_PX, HEIGHT_PX = 2400, 1500
DPI = 100  # 24 x 15 inches at 100 dpi == 2400 x 1500 px, exactly
MIN_PX = 19  # DESIGN floor is 18 px; 19 keeps a margin after rounding to pt

# Top-level directories drawn as boxes. tests/test_diagram.py asserts this
# set equals the top-level source dirs in PLAN §3 and that each exists.
DIR_NODES = ("rules", "core", "store", "agent", "app", "tools")

# ---------------------------------------------------------------- tokens ----
# docs/DESIGN.md §2, light column. Tints marked (derived) are lighter mixes of
# the named token used only here, on paper.
INK = "#15181D"
MUTED = "#4B5563"
LINE = "#C6CBD3"
LINE_STRONG = "#4B5563"
SURFACE = "#F3F4F6"
BG = "#FFFFFF"
ACCENT = "#0B57C2"
ACCENT_TINT = "#E4EDFB"  # derived
ACCENT_TINT_STRONG = "#CFE0F8"  # derived
EMERG = "#B3261E"
EMERG_TINT = "#FDECEA"
URGENT = "#7A4A00"
URGENT_TINT = "#FFF3D6"
REVIEW = "#0E5A60"
REVIEW_TINT = "#E3F2F3"
RULE = "#1B6B2E"
RULE_TINT = "#E6F3EA"  # derived
GEN = "#5B37A8"
GEN_TINT = "#EFE9FA"
MUTED_TINT = "#ECEEF1"
CONTAINER_FILL = "#F9FAFB"  # derived, one step lighter than surface

SANS = "DejaVu Sans"
MONO = "DejaVu Sans Mono"

# Font sizes in px at full size; converted to points for matplotlib.
SIZES = {
    "title": 42,
    "subtitle": 21,
    "container": 21,
    "band": 22,
    "box_title": 22,
    "body": MIN_PX,
    "arrow": MIN_PX,
    "pill": MIN_PX,
    "legend_head": 22,
    "footer": MIN_PX,
}


def pt(px: float) -> float:
    """Pixel height -> point size at this figure's DPI."""
    return px * 72.0 / DPI


# ---------------------------------------------------------------- inputs ----
def read_env() -> dict:
    """Model / store / quiet flag from the environment. Loads .env.local for
    exactly these three names if python-dotenv is present; never touches the
    key."""
    try:
        from dotenv import dotenv_values

        local = dotenv_values(ROOT / ".env.local") if (ROOT / ".env.local").exists() else {}
    except Exception:  # dotenv missing or unreadable: env only
        local = {}

    def pick(name: str, default: str) -> str:
        return os.environ.get(name) or (local.get(name) or "") or default

    return {
        "model": pick("GEMINI_MODEL", "gemini-3.5-flash"),
        "store": pick("STORE", "memory"),
        "model_off": pick("MODEL_OFF", "0"),
    }


def read_pack(path: Path = PACK_PATH) -> dict:
    try:
        pack = json.loads(path.read_text(encoding="utf-8"))
        return {
            "version": str(pack.get("version", "?")),
            "signs": len(pack.get("signs", [])),
            "rules": len(pack.get("rules", [])),
        }
    except Exception:
        return {"version": "?", "signs": 0, "rules": 0}


# ---------------------------------------------------------------- drawing ---
class Canvas:
    def __init__(self):
        self.fig = plt.figure(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI)
        self.fig.patch.set_facecolor(BG)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, WIDTH_PX)
        self.ax.set_ylim(0, HEIGHT_PX)
        self.ax.set_axis_off()
        self.ax.set_facecolor(BG)

    # -- primitives ---------------------------------------------------------
    def text(self, x, y, s, *, px=SIZES["body"], color=INK, weight="normal",
             family=SANS, ha="left", va="center", halo=False, zorder=6, **kw):
        t = self.ax.text(x, y, s, fontsize=pt(px), color=color, fontweight=weight,
                         family=family, ha=ha, va=va, zorder=zorder,
                         linespacing=1.3, **kw)
        if halo:
            t.set_path_effects([patheffects.Stroke(linewidth=6, foreground=BG),
                                patheffects.Normal()])
        return t

    def rect(self, x, y, w, h, *, fill=BG, edge=LINE_STRONG, lw=2.0, ls="-",
             radius=14, zorder=3, alpha=1.0):
        p = FancyBboxPatch((x, y), w, h,
                           boxstyle=f"round,pad=0,rounding_size={radius}",
                           facecolor=fill, edgecolor=edge, linewidth=lw,
                           linestyle=ls, zorder=zorder, alpha=alpha)
        self.ax.add_patch(p)
        return p

    def pill(self, x, y, label, color, tint, *, dashed=False, ha="left"):
        """Tag pill, DESIGN.md §5: tinted fill, 1.5 px border (dashed for
        Simulated), the word in bold. (x, y) is the left-centre; ha='right'
        makes it the right-centre. Returns the pill width."""
        h = 30
        w = len(label) * 11.5 + 30
        x0 = x if ha == "left" else x - w
        self.rect(x0, y - h / 2, w, h, fill=tint, edge=color, lw=1.8,
                  ls=(0, (4, 3)) if dashed else "-", radius=15, zorder=7)
        self.text(x0 + w / 2, y + 1, label, px=SIZES["pill"], color=color,
                  weight="bold", ha="center", zorder=8)
        return w

    def arrow(self, start, end, *, color=INK, lw=2.4, ls="-", both=False,
              halo=False, zorder=5, style="-|>"):
        if both:
            style = "<|-|>"
        ann = self.ax.annotate(
            "", xy=end, xytext=start, zorder=zorder,
            arrowprops=dict(arrowstyle=style, color=color, lw=lw,
                            linestyle=ls, shrinkA=0, shrinkB=0,
                            mutation_scale=24))
        if halo:
            ann.arrow_patch.set_path_effects(
                [patheffects.Stroke(linewidth=lw + 9, foreground=BG),
                 patheffects.Normal()])
        return ann

    def polyline(self, pts, *, color=INK, lw=2.4, ls="-", zorder=5):
        xs, ys = zip(*pts)
        self.ax.plot(xs, ys, color=color, lw=lw, ls=ls, zorder=zorder,
                     solid_capstyle="round", solid_joinstyle="round")

    # -- composite ----------------------------------------------------------
    def box(self, x, y, w, h, title, lines, *, fill=BG, edge=LINE_STRONG,
            lw=2.0, ls="-", title_color=INK, body_color=INK, tag=None,
            big=None, mono=False, zorder=3):
        """Titled box. `lines` is a list of strings or (string, kwargs).
        `big` is an optional emphasised line drawn right under the title.
        `tag` = (label, color, tint, dashed) draws a pill bottom-right."""
        self.rect(x, y, w, h, fill=fill, edge=edge, lw=lw, ls=ls, zorder=zorder)
        pad = 18
        cy = y + h - pad
        self.text(x + pad, cy, title, px=SIZES["box_title"], weight="bold",
                  color=title_color, va="top", zorder=zorder + 3)
        cy -= SIZES["box_title"] + 10
        if big:
            self.text(x + pad, cy, big[0], px=SIZES["box_title"], weight="bold",
                      color=big[1], va="top", zorder=zorder + 3)
            cy -= SIZES["box_title"] + 8
        for line in lines:
            kw = {}
            if isinstance(line, tuple):
                line, kw = line
            self.text(x + pad, cy, line, px=SIZES["body"], va="top",
                      color=kw.get("color", body_color),
                      family=MONO if kw.get("mono", mono) else SANS,
                      weight=kw.get("weight", "normal"), zorder=zorder + 3)
            cy -= 26
        if tag:
            label, color, tint, dashed = tag
            self.pill(x + w - pad, y + pad + 15, label, color, tint,
                      dashed=dashed, ha="right")


def render(out_path: Path | str = DEFAULT_OUT, *, env: dict | None = None,
           pack: dict | None = None) -> Path:
    env = env or read_env()
    pack = pack or read_pack()
    out_path = Path(out_path)
    c = Canvas()
    T = c.text

    # ------------------------------------------------------------ title ----
    T(60, 1462, "Day Three — how a decision is made", px=SIZES["title"], weight="bold")
    T(60, 1416,
      "Postnatal follow-up · the question is “Which mother needs to be seen before tomorrow?” · "
      "rules answer it, the model only writes the prose",
      px=SIZES["subtitle"], color=MUTED)
    T(2340, 1462, "architecture · generated from the repo", px=SIZES["subtitle"],
      color=MUTED, ha="right")

    # ------------------------------------------------- Cloud Run container --
    c.rect(350, 270, 1755, 1122, fill=CONTAINER_FILL, edge=LINE_STRONG, lw=2.2,
           radius=22, zorder=1)
    T(372, 1372,
      "Cloud Run · asia-south1 · service day-three · python:3.12-slim · "
      "uvicorn app.main:app · 0–2 instances · 512 Mi",
      px=SIZES["container"], weight="bold", color=MUTED)

    # ------------------------------------------------- decision-path band --
    band = Rectangle((40, 575), 2350, 493, facecolor=ACCENT_TINT, edgecolor="none",
                     alpha=0.55, zorder=2)
    c.ax.add_patch(band)
    T(60, 1050,
      "DECISION PATH — deterministic · replayable · no model on it",
      px=SIZES["band"], weight="bold", color=ACCENT)

    # ---------------------------------------------- band boxes (y 690–960) --
    BY, BH = 690, 270
    c.box(40, BY, 290, BH, "Nurse's browser", [
        "app/static, no framework",
        "worklist · case · outbox",
        "keypad or free text",
        "seed + clock in the URL",
        "the URL is the state",
    ], edge=ACCENT, lw=2.4, tag=("Observed", ACCENT, ACCENT_TINT, False))

    c.box(390, BY, 300, BH, "app/main.py · FastAPI", [
        "POST seed · advance",
        "POST reply · quiet",
        "GET replay · POST reset",
        "GET worklist · case/{id}",
        "GET outbox · rules",
        "GET health · /",
        "?seed= · ?clock= on all",
    ], edge=LINE_STRONG)

    c.box(750, BY, 300, BH, "app/orchestrator.py", [
        "apply(store, sweep,",
        "      renderer, clock)",
        "one Action → one Event",
        "store.append(event, key)",
        "idempotent on replay",
    ], fill=ACCENT_TINT_STRONG, edge=ACCENT, lw=3.2,
        big=("THE ONLY WRITER", ACCENT))

    # core/ — taller, with sub-block rows
    CX, CY, CW, CH = 1290, BY, 450, 300
    c.rect(CX, CY, CW, CH, fill=RULE_TINT, edge=RULE, lw=2.6)
    T(CX + 18, CY + CH - 18, "core/ — pure, stdlib only", px=SIZES["box_title"],
      weight="bold", va="top")
    rows = [
        "clock.py — injected Clock, no wall clock",
        "schedule.py — Contact Ladder D1…D42",
        "gate.py — Danger-Sign Gate → Verdict",
        "routing.py · slots.py → Action[] + rule_id",
        "sweep.py — run_sweep() → SweepResult",
    ]
    ry = CY + CH - 18 - SIZES["box_title"] - 14
    for r in rows:
        c.rect(CX + 16, ry - 30, CW - 32, 30, fill=BG, edge=RULE, lw=1.2, radius=6,
               zorder=4)
        T(CX + 28, ry - 15, r, px=SIZES["body"], zorder=7)
        ry -= 36
    T(CX + 18, ry - 4, "no genai · no network · no env · no open()",
      px=SIZES["body"], color=MUTED, va="top")
    c.pill(CX + CW - 18, CY + CH - 18 - 13, "Rule", RULE, RULE_TINT, ha="right")

    c.box(1800, BY, 280, BH, "store/ — event log", [
        "append-only events",
        "MemoryStore (+JSON file)",
        "FirestoreStore on GCP",
        "state = reduce(events)",
        "read-only view → agent/",
    ], fill=SURFACE, edge=LINE_STRONG)

    c.box(2130, BY, 250, BH, "Firestore", [
        "asia-south1",
        "STORE=firestore",
        "ns/{seed}/cases/{id}",
        "create() = idempotent",
        "local: STORE=memory",
    ], edge=LINE_STRONG, ls=(0, (6, 4)))

    # ------------------------------------------------- band arrows ---------
    c.arrow((330, 825), (390, 825))
    T(360, 985, "keypad digit or free text · Observed", ha="center", color=MUTED)
    c.arrow((690, 825), (750, 825))
    T(720, 985, "sweep · reply", ha="center", color=MUTED)
    # orchestrator <-> core, two arrows with stacked labels in the gap
    c.arrow((1050, 880), (1290, 880))
    T(1170, 910, "events snapshot", ha="center", va="bottom")
    T(1170, 933, "+ Clock + pack →", ha="center", va="bottom")
    c.arrow((1290, 770), (1050, 770))
    T(1170, 745, "← Verdict · Action[]", ha="center", va="top")
    T(1170, 722, "rule_id + source_quote", ha="center", va="top")
    # orchestrator -> store, routed under core
    c.polyline([(890, 690), (890, 605), (1840, 605), (1840, 690)])
    c.arrow((1840, 640), (1840, 690))
    c.arrow((890, 640), (890, 690))
    T(1170, 628, "append Event{type, tag, rule_id, key} ← → read events", ha="center",
      va="bottom", halo=True)
    # store -> Firestore
    c.arrow((2080, 825), (2130, 825))
    T(2105, 985, "create() idempotent", ha="center", color=MUTED)

    # ------------------------------------------------- model layer (top) ---
    # red dashed boundary around agent/
    c.rect(1270, 1092, 820, 268, fill="none", edge=EMERG, lw=3.2, ls=(0, (9, 6)),
           radius=18, zorder=2)
    T(1290, 1345, "NO WRITE TOOL — agent/ cannot import store (tests/test_boundary.py)",
      px=SIZES["band"], weight="bold", color=EMERG)

    c.box(1290, 1110, 780, 215,
          "agent/ — model layer (google-genai + ADK)", [
              "writer.py — ADK LlmAgent with four read-only tools:",
              "read_case · read_rule · translate · draft_message  (ReadOnlyStoreView)",
              "reader.py — free text → SymptomForm, values true | unknown, never false",
              "gemini_client.py — timeout · JSON schema · cache · loud MODEL_FALLBACK",
              "drafts Hindi + English escalation prose; routine check-ins are templates",
          ], edge=GEN, lw=2.4)
    c.pill(2070 - 18, 1325 - 18 - 13, "Generated", GEN, GEN_TINT, ha="right")

    # Quiet Mode switch box (above the orchestrator)
    QX, QY, QW, QH = 690, 1110, 360, 215
    c.box(QX, QY, QW, QH, "Quiet Mode", [
        "env MODEL_OFF=1 or",
        "POST /api/quiet {on}",
        "ON → templates.json (Rule)",
        "reader off → HUMAN_REVIEW",
        "same decisions either way",
    ], fill=REVIEW_TINT, edge=REVIEW, lw=2.4)
    # switch glyph (track + knob), state read from env
    on = env["model_off"] == "1"
    tx, ty = QX + QW - 18 - 76, QY + QH - 18 - 28
    c.rect(tx, ty, 76, 30, fill=REVIEW if on else BG, edge=REVIEW, lw=2, radius=15,
           zorder=7)
    knob = Circle((tx + (58 if on else 18), ty + 15), 11, facecolor=BG if on else REVIEW,
                  edgecolor=REVIEW, lw=1.5, zorder=8)
    c.ax.add_patch(knob)
    T(tx - 10, ty + 15, "ON" if on else "OFF", px=SIZES["pill"], weight="bold",
      color=REVIEW, ha="right")

    c.box(2130, 1110, 250, 215, "Gemini API", [
        "google-genai SDK",
        (env["model"], {"mono": True}),
        "JSON schema output",
        "20 s timeout · cache",
        "budget 12 calls/run",
        "fails loud, tagged",
    ], fill=GEN_TINT, edge=GEN, lw=2.4)

    # model-layer arrows
    c.arrow((890, 960), (890, 1110))  # orchestrator -> switch
    T(905, 1035, "render(intent, lang)", ha="left")
    c.arrow((1050, 1215), (1290, 1215))  # switch -> agent (model on)
    T(1170, 1240, "model ON", ha="center", va="bottom", color=MUTED)
    c.arrow((2070, 1215), (2130, 1215))  # agent -> Gemini
    # store -> agent: read-only view (dashed, grey)
    c.arrow((1940, 960), (1940, 1110), color=MUTED, ls=(0, (5, 4)), lw=2.0)
    T(1925, 1015, "ReadOnlyStoreView · read only", ha="right", color=MUTED)
    # agent -> orchestrator: the red arrow, the only thing that crosses back
    c.arrow((1400, 1110), (1050, 960), color=EMERG, lw=3.2, halo=True, zorder=6)
    T(1265, 1062, "prose + SymptomForm only — no write tool", ha="left", va="bottom",
      weight="bold", color=EMERG)

    # ------------------------------------------------- lower zone ----------
    LY, LH = 300, 260
    c.box(390, LY, 300, LH, "tools/ — dev only", [
        "demo.py — morning worklist",
        "quiet_diff.py — on vs off",
        "adversarial.py — miss rate",
        "diagram.py — this PNG",
    ], edge=LINE, lw=2.0)

    c.box(750, LY, 300, LH, "Sources (verbatim)", [
        "WHO postnatal care 2022",
        "WHO IMCI / PSBI newborn signs",
        "HBNC home-visit ladder",
        "per rule: source_id,",
        "source_quote, source_url",
    ], fill=SURFACE, edge=MUTED, lw=2.0)

    c.box(1290, LY, 450, LH,
          f"rules/postnatal.v1.json — v{pack['version']}", [
              "validated by rules/schema.json",
              f"{pack['signs']} signs · {pack['rules']} rules · Hindi + keypad",
              "ladder: WHO D1 D3 D7–14 D42 · HBNC D3…D42",
              "danger signs → routes, with precedence",
              "silence policy · clinic slot table",
          ], fill=RULE_TINT, edge=RULE, lw=2.6, tag=("Rule", RULE, RULE_TINT, False))

    c.box(1800, LY, 280, LH, "Outbox — simulated", [
        "SMS · IVR · WhatsApp",
        "pager to on-call nurse",
        "nothing is ever delivered",
        "GET /api/outbox",
        "Hindi + English text",
    ], fill=MUTED_TINT, edge=MUTED, lw=2.0, ls=(0, (5, 4)),
        tag=("Simulated", MUTED, MUTED_TINT, True))

    # lower arrows
    c.arrow((1050, 430), (1290, 430))
    T(1170, 455, "copied verbatim", ha="center", va="bottom", color=MUTED)
    c.arrow((1515, 560), (1515, 690), halo=True, zorder=6)  # rules -> core
    T(1530, 625, "pack + source_quote", ha="left")
    c.arrow((2020, 690), (2020, 560))  # store -> outbox
    T(2005, 637, "message +", ha="right")
    T(2005, 613, "page events", ha="right")

    # ------------------------------------------------- legend --------------
    T(60, 228, "Tags — every value in the UI and every event carries one",
      px=SIZES["legend_head"], weight="bold")
    legend = [
        ("Observed", ACCENT, ACCENT_TINT, False,
         "typed by a human in this session:", "the judge's free text, a nurse click"),
        ("Rule", RULE, RULE_TINT, False,
         "computed by core/ from the pack;", "carries rule_id + verbatim source_quote"),
        ("Simulated", MUTED, MUTED_TINT, True,
         "synthetic by design: cohort, clock,", "keypad replies, channels, slot table"),
        ("Generated", GEN, GEN_TINT, False,
         "model output; carries the model string", "and degraded=true on fallback"),
    ]
    for i, (label, color, tint, dashed, l1, l2) in enumerate(legend):
        x = 60 + i * 585
        c.pill(x, 190, label, color, tint, dashed=dashed)
        T(x, 155, l1, color=MUTED)
        T(x, 132, l2, color=MUTED)

    # ------------------------------------------------- footer --------------
    T(60, 72,
      f"rules/postnatal.v1.json v{pack['version']} · {pack['signs']} signs · "
      f"{pack['rules']} rules   |   GEMINI_MODEL={env['model']}   |   "
      f"STORE={env['store']}   |   MODEL_OFF={env['model_off']}",
      px=SIZES["footer"], family=MONO)
    T(60, 42,
      "Independent prototype on synthetic data · not a government, NHM or WHO product · "
      "regenerate with `make diagram` (tools/diagram.py, matplotlib only)",
      px=SIZES["footer"], color=MUTED)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    c.fig.savefig(out_path, dpi=DPI, facecolor=BG,
                  metadata={"Software": "tools/diagram.py"})
    plt.close(c.fig)
    return out_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default=str(DEFAULT_OUT), help="output PNG path")
    args = p.parse_args(argv)
    out = render(args.out)
    size = out.stat().st_size
    print(f"wrote {out} ({WIDTH_PX}x{HEIGHT_PX}, {size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
