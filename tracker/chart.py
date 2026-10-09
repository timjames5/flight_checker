"""Small PNG line chart of the cheapest nonstop price per cabin over time."""

from __future__ import annotations

import datetime as dt
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

SURFACE = "#ffffff"
LINES = ["#2a78d6", "#c2560c", "#2f8f4e", "#7a4fc9"]  # one per cabin, in config order
TEXT = "#0b0b0b"
MUTED = "#52514e"
GRID = "#e4e3df"


def price_chart_png(series: dict[str, list[tuple[dt.datetime, float]]]) -> bytes:
    """One line per cabin; series maps cabin name to (time, price) points."""
    fig, ax = plt.subplots(figsize=(5.6, 2.2 if len(series) == 1 else 2.8), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for i, (name, points) in enumerate(series.items()):
        color = LINES[i % len(LINES)]
        times = [t.replace(tzinfo=None) for t, _ in points]
        prices = [p for _, p in points]
        ax.plot(times, prices, color=color, linewidth=1.5, marker="o", markersize=3.5,
                markeredgecolor=SURFACE, markeredgewidth=1, solid_capstyle="round", zorder=3,
                label=name)

        low_i = min(range(len(prices)), key=prices.__getitem__)
        ax.annotate(f"£{prices[-1]:,.0f}", (times[-1], prices[-1]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=7.5, color=TEXT,
                    fontweight="bold")
        if low_i != len(prices) - 1:
            ax.annotate(f"low £{prices[low_i]:,.0f}", (times[low_i], prices[low_i]),
                        xytext=(0, -11), textcoords="offset points", ha="center",
                        fontsize=6.5, color=MUTED)

    if len(series) > 1:
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.18), ncol=len(series),
                  frameon=False, fontsize=7, labelcolor=MUTED, handlelength=1.6)

    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"£{v:,.0f}"))
    ax.yaxis.set_major_locator(plt.MaxNLocator(4))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=7))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.tick_params(colors=MUTED, labelsize=7, length=0, pad=4)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.margins(x=0.06, y=0.25)

    fig.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE)
    plt.close(fig)
    return buf.getvalue()

