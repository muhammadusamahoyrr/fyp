r"""
build_figures.py — regenerate every figure in the paper from measured numbers.

Why a script rather than drawn images: the same figures are consumed by both the
LaTeX build (\includegraphics) and the .docx build (add_picture), and hand-made
images drift from the tables they illustrate. Every value below is transcribed
from a results file and cross-checked against the table it appears in, so a
figure cannot silently disagree with the text.

NOTHING HERE IS SYNTHETIC. Figures we could legitimately draw but have no data
for -- risk-coverage curves, calibration/reliability diagrams, confusion
matrices -- are deliberately absent, because the calibration layer is unfitted
and the labelled set does not yet exist (Section V-I). Plotting them from
placeholder numbers would be the exact failure the paper reports finding in its
own earlier results.

Usage:
    backend/venv/Scripts/python.exe paper/build_figures.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent / "figures"
OUT.mkdir(exist_ok=True)

# IEEE two-column: a single-column figure is 3.4in wide. Type must stay legible
# at that width, so nothing below 7pt.
plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif"],
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 8,
    "xtick.labelsize": 7.5,
    "ytick.labelsize": 7.5,
    "legend.fontsize": 7.5,
    "axes.linewidth": 0.6,
    "figure.dpi": 400,
    "pdf.fonttype": 42,      # embed real fonts, not paths
    "savefig.format": "pdf",
})

INK = "#1a1a1a"
GREY = "#9e9e9e"

# Colourblind-safe palette (Okabe--Ito). No red/green pair appears together,
# so the figures survive deuteranopia and protanopia, and every encoding is
# also carried by position, hatch or marker so nothing depends on colour alone.
BLUE = "#0072B2"   # answerable / weighted
ORANGE = "#E69F00"  # unanswerable / fixed
TEAL = "#009E73"
VERM = "#D55E00"
PURPLE = "#CC79A7"
SKY = "#56B4E9"

BASE = "#b0b7bd"
CONST = SKY
GEN = "#0072B2"


def _clean(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=2.5, width=0.6, colors=INK)
    ax.yaxis.grid(True, color="#e3e3e3", lw=0.5)
    ax.set_axisbelow(True)


# ─────────────────────────────────────────────────────────────────────────────
# Fig. 4 — the collapse: gain measured in-distribution against gain measured
# out-of-distribution, for two independently trained models.
# ─────────────────────────────────────────────────────────────────────────────
def fig_transfer_collapse(path: Path) -> None:
    models = ["general\n(4,692 pairs, 5 domains)",
              "constitutional\n(471 pairs, 1 domain)"]
    in_dist = [0.265, 0.165]
    out_dist = [0.024, -0.003]

    fig, ax = plt.subplots(figsize=(3.4, 2.15))
    # Both right-hand endpoints sit within 0.03 of zero, so their labels would
    # collide with each other and with the zero rule. Push them apart by hand.
    right_dy = [7, -9]
    for i, (a, b) in enumerate(zip(in_dist, out_dist)):
        ax.plot([0, 1], [a, b], color=GREY, lw=1.0, zorder=1)
        ax.scatter([0], [a], s=34, color=GEN, zorder=3, edgecolor=INK, lw=0.5)
        ax.scatter([1], [b], s=34, color="#c25b5b", zorder=3,
                   edgecolor=INK, lw=0.5)
        ax.annotate(f"{a:+.3f}", (0, a), xytext=(-6, 0),
                    textcoords="offset points", ha="right", va="center",
                    fontsize=7.5)
        ax.annotate(f"{b:+.3f}", (1, b), xytext=(7, right_dy[i]),
                    textcoords="offset points", ha="left", va="center",
                    fontsize=7.5)
        # Name each line just right of its start, along the slope.
        ax.annotate(models[i], (0.06, a - 0.012), xytext=(0, 0),
                    textcoords="offset points", ha="left", va="top",
                    fontsize=6.6, color="#4a4a4a")

    ax.axhline(0, color=INK, lw=0.7, ls=(0, (3, 2)))
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["measured on its own\ntraining distribution",
                        "measured on a different\nquestion style"])
    ax.set_xlim(-0.42, 1.42)
    ax.set_ylabel(r"$\Delta$ Hit@1 over base")
    ax.set_ylim(-0.06, 0.32)
    _clean(ax)
    ax.xaxis.grid(False)
    fig.tight_layout(pad=0.3)
    fig.savefig(path, bbox_inches="tight")
    fig.savefig(path.with_suffix(".png"), bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  wrote {path.name} and {path.with_suffix('.png').name}")


# ─────────────────────────────────────────────────────────────────────────────
# Fig. 1 — the governance pipeline. Drawn rather than screenshotted so it stays
# consistent with the node names in Section III.
# ─────────────────────────────────────────────────────────────────────────────
def fig_pipeline(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(3.4, 3.5))
    ax.set_xlim(0, 10.7)
    ax.set_ylim(0, 15.4)
    ax.axis("off")

    def box(y, text, h=1.15, w=8.4, x=0.8, fc="#ffffff", ec=INK, fs=7.4,
            bold=False, ls="-"):
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.08,rounding_size=0.12",
            fc=fc, ec=ec, lw=0.7, ls=ls, zorder=2))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, color=INK, zorder=3,
                fontweight="bold" if bold else "normal")

    def arrow(y0, y1, x=5.0, label=None, color=INK):
        ax.add_patch(FancyArrowPatch((x, y0), (x, y1), color=color, lw=0.7,
                                     arrowstyle="-|>", mutation_scale=7,
                                     zorder=1))
        if label:
            ax.text(x + 0.18, (y0 + y1) / 2, label, fontsize=6.5,
                    ha="left", va="center", color=color)

    box(14.0, "user query  (English / Urdu / Roman Urdu)", fc="#eef2f5")
    arrow(14.0, 13.35)
    box(12.2, "script detection and Roman-Urdu normalisation\n"
              "(observed script overrides any declared label)")
    arrow(12.2, 11.55)
    box(10.4, "ANSWERABILITY GATE\nis this the KIND of fact a statute can "
              "state?", bold=True, fc="#f6ecec", ec="#a33")
    ax.text(9.35, 10.98, "refuse", fontsize=6.5, color="#a33",
            ha="right", va="center")
    ax.add_patch(FancyArrowPatch((9.2, 10.98), (9.9, 10.98), color="#a33",
                                 lw=0.7, arrowstyle="-|>", mutation_scale=6))
    arrow(10.4, 9.75)
    box(8.6, "hybrid retrieval\nBM25 (0.6)  $\\oplus$  dense e5 (0.4), "
             "province-filtered")
    arrow(8.6, 7.95)
    box(6.8, "deterministic statutory engines\n(court fee, limitation, "
             "shares) — admitted as evidence")
    arrow(6.8, 6.15)
    box(5.0, "three confidence signals\nlexical (local IDF) · embedding "
             "similarity · grader")
    arrow(5.0, 4.35)
    box(3.2, "ARBITRATION:  expected loss over a harm matrix\n"
             "answer  |  clarify  |  refuse", bold=True, fc="#eef2f5")
    arrow(3.2, 2.55)
    box(1.4, "grounding verification, then the SINGLE enforced\n"
             "output path — every turn writes a provenance record")
    arrow(1.4, 0.75)
    box(-0.1, "answer  ·  clarifying question  ·  refusal", h=0.85,
        fc="#eef2f5")

    fig.tight_layout(pad=0.2)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {path.name}")


# ─────────────────────────────────────────────────────────────────────────────
# Fig. 2 — the lexical signal, fixed vocabulary against local IDF weighting.
# Replaces the per-query table: the claim is the SIGN FLIP in separation, which
# a reader should see rather than compute by scanning eleven rows.
# Source: paper Table IV (scoring diagnostic).
# ─────────────────────────────────────────────────────────────────────────────
def fig_lexical(path: Path) -> None:
    answerable = [
        ("punishment for theft (PPC)", 0.438, 0.569),
        ("eviction without notice", 0.000, 0.358),
        ("grounds for khula", 0.444, 0.162),
        ("refusal to register an FIR", 0.053, 0.098),
        ("fundamental rights", 0.000, 0.184),
        ("limitation period, civil suit", 0.056, 0.216),
        ("dishonoured cheque (s. 489-F)", 0.462, 0.160),
        ("share in Islamic inheritance", 0.000, 0.061),
    ]
    unanswerable = [
        ("current stamp-duty rate", 0.789, 0.118),
        ("cases pending in the LHC, 2019", 0.733, 0.227),
        ("my lawyer's phone number", 0.050, 0.063),
    ]
    rows = answerable + unanswerable
    n_a = len(answerable)

    fig, ax = plt.subplots(figsize=(3.4, 3.05))
    y = list(range(len(rows)))[::-1]
    h = 0.38
    ax.barh([v + h / 2 for v in y], [r[1] for r in rows], h, label="fixed vocabulary",
            color=ORANGE, edgecolor=INK, lw=0.4)
    ax.barh([v - h / 2 for v in y], [r[2] for r in rows], h, label="local IDF weighting",
            color=BLUE, edgecolor=INK, lw=0.4)

    # Divider between the two query classes: the whole argument is that the
    # blocks should NOT be ordered the way the orange bars order them.
    ax.axhline(y[n_a] + 0.5, color=INK, lw=0.8)

    # Class labels go OUTSIDE the right spine, rotated. Placing them inside
    # collides with the two longest bars, which are precisely the unanswerable
    # queries the figure exists to show.
    for lab, block in (("ANSWERABLE", y[:n_a]), ("UNANSWERABLE", y[n_a:])):
        ax.text(1.012, sum(block) / len(block), lab, fontsize=6.4, color=INK,
                ha="center", va="center", rotation=90, fontweight="bold",
                transform=ax.get_yaxis_transform())

    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=6.4)
    ax.set_xlabel("lexical score")
    ax.set_xlim(0, 0.84)
    ax.legend(frameon=False, loc="lower right", handlelength=1.1, fontsize=6.8)
    _clean(ax)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color="#e3e3e3", lw=0.5)

    # Separations are quoted from the paper's own rounded means (0.181/0.524
    # and 0.226/0.136), not recomputed here: recomputing from the unrounded
    # values gives -0.342, and a figure that disagrees with the text by a digit
    # is exactly the kind of drift this script exists to prevent.
    ax.set_title("separation (A $-$ U):   fixed $-$0.343"
                 "      weighted $+$0.090", fontsize=7.2, pad=5)
    fig.tight_layout(pad=0.3)
    fig.savefig(path, bbox_inches="tight")
    fig.savefig(path.with_suffix(".png"), bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  wrote {path.name} and {path.with_suffix('.png').name}")


# ─────────────────────────────────────────────────────────────────────────────
# Fig. 5 — coverage against the harm ratio. Replaces the sweep table: the point
# is that the two curves move TOGETHER, which is a shape, not a set of numbers.
# Source: paper Table V.
# ─────────────────────────────────────────────────────────────────────────────
def fig_rho(path: Path) -> None:
    rho = [10, 4, 2, 1, 0.5, 0.1]
    thr = [0.091, 0.200, 0.333, 0.500, 0.667, 0.909]
    ans_a = [9 / 9, 9 / 9, 7 / 9, 1 / 9, 0, 0]
    ans_u = [4 / 4, 4 / 4, 2 / 4, 0, 0, 0]

    fig, ax = plt.subplots(figsize=(3.4, 2.2))
    ax.plot(thr, ans_a, "-o", color=BLUE, lw=1.2, ms=4.2,
            label="answerable (9)", zorder=3)
    ax.plot(thr, ans_u, "--s", color=ORANGE, lw=1.2, ms=4.0,
            label="unanswerable (4)", zorder=3)

    ax.axvline(0.200, color=INK, lw=0.7, ls=(0, (2, 2)), zorder=1)
    # Sits above the crossing point: at y=0.5 it lands on the orange curve.
    ax.annotate("deployed\nthreshold\n" + r"($\rho = 4$)", xy=(0.200, 0.52),
                xytext=(0.235, 0.78), fontsize=6.5, color=INK,
                ha="left", va="center")

    ax.set_xlabel(r"decision threshold $1/(1+\rho)$" "\n"
                  r"(labels: harm ratio $\rho$)")
    ax.set_ylabel("fraction answered")
    ax.set_ylim(-0.06, 1.12)
    ax.set_xlim(0.02, 0.97)
    ax.set_xticks(thr)
    ax.set_xticklabels([f"{t:.2f}\n{r:g}" for t, r in zip(thr, rho)], fontsize=6.4)
    ax.legend(frameon=False, loc="upper right", handlelength=1.6, fontsize=6.8)
    _clean(ax)
    fig.tight_layout(pad=0.3)
    fig.savefig(path, bbox_inches="tight")
    fig.savefig(path.with_suffix(".png"), bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  wrote {path.name} and {path.with_suffix('.png').name}")


# ─────────────────────────────────────────────────────────────────────────────
# Fig. 1 — corpus by collection and tier. Replaces the counts table: the table
# gave totals, this also shows the coverage gap, which is the point.
# ─────────────────────────────────────────────────────────────────────────────
def fig_corpus(path: Path) -> None:
    names = ["Civil\n(incl. CPC)", "Criminal", "Constit-\nutional",
             "Family\n(20 acts)"]
    federal = [2949, 2839, 1736, 910]
    punjab = [1064, 465, 0, 79]

    fig, ax = plt.subplots(figsize=(3.4, 1.95))
    x = range(len(names))
    ax.bar(x, federal, 0.62, label="federal", color=BLUE,
           edgecolor=INK, lw=0.4)
    ax.bar(x, punjab, 0.62, bottom=federal, label="provincial (Punjab)",
           color=ORANGE, edgecolor=INK, lw=0.4)
    for i, (f, p) in enumerate(zip(federal, punjab)):
        ax.annotate(f"{f + p:,}", (i, f + p), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=7)
    # Point to the provincial bar layer highlighting Punjab-only coverage across devolved subjects
    ax.annotate("only Punjab\nrepresented", (1.1, 3100), xytext=(1.8, 3800),
                fontsize=6.4, color=VERM, ha="center", va="center",
                arrowprops=dict(arrowstyle="-|>", color=VERM, lw=0.6,
                                mutation_scale=6))
    ax.set_xticks(list(x))
    ax.set_xticklabels(names, fontsize=6.8)
    ax.set_ylabel("indexed chunks")
    ax.set_ylim(0, 4600)
    ax.legend(frameon=False, loc="upper right", handlelength=1.1, fontsize=6.8)
    _clean(ax)
    ax.xaxis.grid(False)
    fig.tight_layout(pad=0.3)
    fig.savefig(path, bbox_inches="tight")
    fig.savefig(path.with_suffix(".png"), bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  wrote {path.name} and {path.with_suffix('.png').name}")


# ─────────────────────────────────────────────────────────────────────────────
# Fig. 3 — rank of the correct statute after each stage, at both depths.
# Replaces the rerank table and the prose that walked through it.
# ─────────────────────────────────────────────────────────────────────────────
def fig_rerank(path: Path) -> None:
    stages = ["first\nstage", "+ scope\nrules", "+ cross-\nencoder"]
    k10 = [3, 1, 10]
    k50 = [4, 1, 24]

    fig, ax = plt.subplots(figsize=(3.4, 2.05))
    x = [0, 1, 2]
    ax.plot(x, k10, "-o", color=BLUE, lw=1.3, ms=5, label="pool $k=10$", zorder=3)
    ax.plot(x, k50, "--s", color=VERM, lw=1.3, ms=4.6, label="pool $k=50$", zorder=3)
    # The axis is inverted, so an "up" offset in display space moves towards
    # rank 1. Separate the two series left/right as well as up/down, or the
    # labels collide wherever the lines nearly touch.
    for xi, (a, b) in enumerate(zip(k10, k50)):
        ax.annotate(str(a), (xi, a), xytext=(-11, 4), textcoords="offset points",
                    ha="right", fontsize=7, color=BLUE)
        ax.annotate(str(b), (xi, b), xytext=(11, -7), textcoords="offset points",
                    ha="left", fontsize=7, color=VERM)
    ax.axhspan(0.4, 1.6, color="#009E73", alpha=0.13, zorder=0)
    ax.annotate("deterministic rule: rank 1, $<$1 ms", (0.55, 5.4),
                fontsize=6.4, color=TEAL, ha="left", va="center")
    ax.annotate("0.73 s / 2.43 s", (2, 15.5), fontsize=6.4, color=VERM,
                ha="center", va="center")
    ax.set_xticks(x)
    ax.set_xticklabels(stages, fontsize=7)
    ax.set_xlim(-0.45, 2.45)
    ax.set_ylabel("rank of correct statute")
    ax.invert_yaxis()
    ax.set_yticks([1, 5, 10, 15, 20, 25])
    _clean(ax)
    ax.xaxis.grid(False)
    ax.legend(frameon=False, loc="lower left", handlelength=1.6, fontsize=6.8)
    fig.tight_layout(pad=0.3)
    fig.savefig(path, bbox_inches="tight")
    fig.savefig(path.with_suffix(".png"), bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  wrote {path.name} and {path.with_suffix('.png').name}")


if __name__ == "__main__":
    print(f"\n  figures -> {OUT}")
    fig_corpus(OUT / "fig1_corpus.pdf")
    fig_lexical(OUT / "fig2_lexical.pdf")
    fig_rerank(OUT / "fig3_rerank.pdf")
    fig_transfer_collapse(OUT / "fig4_transfer_collapse.pdf")
    print()
