"""Generate the TAMP-OS README header image."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

# ── Canvas ─────────────────────────────────────────────────────────────────
W, H = 16, 5.6           # inches  (→ 1600 × 560 px at 100 dpi)
fig, ax = plt.subplots(figsize=(W, H))
fig.patch.set_facecolor("#0d1117")
ax.set_facecolor("#0d1117")
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.axis("off")

# ── Palette ────────────────────────────────────────────────────────────────
BG        = "#0d1117"
CARD_BG   = "#161b22"
ACCENT    = "#2188ff"
ACCENT2   = "#58a6ff"
MUTED     = "#8b949e"
WHITE     = "#e6edf3"
GREEN     = "#3fb950"

# ── Title block (top, full width) ──────────────────────────────────────────
ax.text(0.55, 5.15, "TAMP-OS",
        color=WHITE, fontsize=42, fontweight="bold",
        fontfamily="DejaVu Sans", va="center")

ax.text(0.55, 4.52,
        "Open-Source Tactile Lithograph Pipeline",
        color=ACCENT2, fontsize=14, fontfamily="DejaVu Sans", va="center")

ax.text(0.55, 4.02,
        "Any FDM printer  ·  No proprietary hardware  ·  Fully scriptable",
        color=MUTED, fontsize=10, fontfamily="DejaVu Sans", va="center")

# Thin accent line
ax.plot([0.55, 7.5], [3.72, 3.72], color=ACCENT, linewidth=1.2, alpha=0.5)

# Built-on attribution
ax.text(0.55, 3.42,
        "Built on  TAMP  (Faulkner et al., Science 2026)",
        color=MUTED, fontsize=9, fontfamily="DejaVu Sans", va="center",
        style="italic")

# ── Pipeline cards (bottom row, full width) ────────────────────────────────
steps = [
    ("①", "Microscopy\nImage",    ".PNG / .JPG",     "#1f6feb"),
    ("②", "Height\nMap",          "Grayscale array",  "#388bfd"),
    ("③", "STL\nMesh",            "Watertight solid", "#58a6ff"),
    ("④", "G-code",               "Any slicer",       "#79c0ff"),
    ("⑤", "Tactile\nLithograph",  "Any FDM printer",  GREEN),
]

n        = len(steps)
margin   = 0.55          # left/right margin
gap      = 0.28          # gap between cards
card_h   = 2.30
y_bot    = 0.52
total_w  = W - 2 * margin
card_w   = (total_w - (n - 1) * gap) / n

for i, (num, label, sub, color) in enumerate(steps):
    x0 = margin + i * (card_w + gap)

    # Card shadow
    shadow = FancyBboxPatch(
        (x0 + 0.04, y_bot - 0.04), card_w, card_h,
        boxstyle="round,pad=0.05",
        facecolor="#000000", edgecolor="none", alpha=0.4, zorder=1
    )
    ax.add_patch(shadow)

    # Card body
    card = FancyBboxPatch(
        (x0, y_bot), card_w, card_h,
        boxstyle="round,pad=0.05",
        facecolor=CARD_BG, edgecolor=color, linewidth=1.8, zorder=2
    )
    ax.add_patch(card)

    # Top colour bar
    bar = FancyBboxPatch(
        (x0, y_bot + card_h - 0.36), card_w, 0.36,
        boxstyle="round,pad=0.0",
        facecolor=color, edgecolor="none", alpha=0.22, zorder=3
    )
    ax.add_patch(bar)

    cx = x0 + card_w / 2

    # Step number
    ax.text(cx, y_bot + card_h - 0.18, num,
            color=color, fontsize=13, fontweight="bold",
            ha="center", va="center", zorder=4)

    # Main label
    ax.text(cx, y_bot + card_h * 0.50, label,
            color=WHITE, fontsize=12.5, fontweight="bold",
            ha="center", va="center", zorder=4,
            multialignment="center")

    # Subtitle
    ax.text(cx, y_bot + 0.24, sub,
            color=MUTED, fontsize=8.5,
            ha="center", va="center", zorder=4,
            multialignment="center")

    # Arrow to next card
    if i < n - 1:
        ax.annotate("",
            xy=(x0 + card_w + gap, y_bot + card_h / 2),
            xytext=(x0 + card_w, y_bot + card_h / 2),
            arrowprops=dict(
                arrowstyle="-|>",
                color=ACCENT2, lw=1.8,
                mutation_scale=15,
            ),
            zorder=5
        )

# ── Footer tag ─────────────────────────────────────────────────────────────
ax.text(W / 2, 0.20,
        "github.com/nagova/TAMP-OS",
        color=MUTED, fontsize=8.5, ha="center", va="center",
        fontfamily="DejaVu Sans")

# ── Save ───────────────────────────────────────────────────────────────────
out = "C:/Users/vazquez/TAMP-OS/assets/tamp_os_header.png"
fig.savefig(out, dpi=100, bbox_inches="tight",
            facecolor=fig.get_facecolor())
plt.close(fig)
print(f"Saved: {out}")
