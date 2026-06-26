#!/usr/bin/env python3
"""
Detailed per-experiment plots + summary table.
For project submission PDF.
"""
import csv, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

RESULTS_DIR = os.path.dirname(os.path.abspath(__file__))
SLO = 0.5

def load(name):
    path = os.path.join(RESULTS_DIR, f"{name}.csv")
    if not os.path.exists(path):
        return None
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            p = row["p99_latency"]
            r = row["replicas"]
            rows.append({
                "elapsed":  float(row["elapsed"]),
                "p99":      float(p) if p not in ("","None","nan") else np.nan,
                "replicas": int(r) if r not in ("","None") else 0,
                "queue":    float(row.get("queue_depth","0") or 0),
            })
    return rows

def slo_compliance(data):
    vals = [d["p99"] for d in data if not np.isnan(d["p99"])]
    if not vals:
        return 0
    ok = sum(1 for v in vals if v <= SLO)
    return ok / len(vals) * 100

def plot_all():
    exps = {
        "custom": ("Custom C++ Autoscaler", "#2196F3"),
        "hpa70":  ("HPA 70% CPU",           "#FF9800"),
        "hpa90":  ("HPA 90% CPU",           "#F44336"),
    }

    # ── Figure 1: Main comparison (required by slide 17) ──────
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    fig.suptitle(
        "Elastic ML Inference Serving — Autoscaler Comparison\n"
        "Technische Universität Ilmenau · Cloud Computing APL 2026",
        fontsize=13, fontweight="bold", y=0.98)

    ax_lat, ax_rep = axes
    any_data = False

    for key, (label, color) in exps.items():
        data = load(key)
        if not data:
            print(f"  Skipping {key} — no CSV")
            continue
        any_data = True
        t   = [d["elapsed"]  for d in data]
        lat = [d["p99"]      for d in data]
        rep = [d["replicas"] for d in data]
        comp = slo_compliance(data)

        ax_lat.plot(t, lat,
                    label=f"{label} (SLO compliance: {comp:.0f}%)",
                    color=color, linewidth=2,
                    marker="o", markersize=4)
        ax_rep.step(t, rep,
                    label=label, color=color,
                    linewidth=2.5, where="post")

    if not any_data:
        print("No data found.")
        return

    # Latency panel
    ax_lat.axhline(SLO, color="red", linestyle="--",
                   linewidth=2, label="SLO limit = 0.5s", zorder=5)
    ax_lat.fill_between(
        [min(d["elapsed"] for k in exps
             for d in (load(k) or [{"elapsed":0}]))],
        SLO, 2, alpha=0.05, color="red")
    ax_lat.set_ylabel("P99 Latency (seconds)", fontsize=12)
    ax_lat.set_title("P99 Request Latency Over Time", fontsize=12)
    ax_lat.legend(fontsize=9, loc="upper left")
    ax_lat.grid(True, alpha=0.3)
    ax_lat.set_ylim(0, 2)
    ax_lat.set_xlabel("Time (seconds)", fontsize=11)
    ax_lat.annotate("← SLO violation zone",
                    xy=(50, 0.6), fontsize=9, color="red", alpha=0.7)

    # Replica panel
    ax_rep.set_ylabel("Active Replicas (CPU cores)", fontsize=12)
    ax_rep.set_title("Inference Pod Replica Count Over Time", fontsize=12)
    ax_rep.legend(fontsize=9, loc="upper left")
    ax_rep.grid(True, alpha=0.3)
    ax_rep.set_ylim(0, 4)
    ax_rep.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax_rep.set_xlabel("Time (seconds)", fontsize=11)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    out = os.path.join(RESULTS_DIR, "comparison_final.png")
    plt.savefig(out, dpi=180, bbox_inches="tight")
    print(f"Saved: {out}")
    plt.close()

    # ── Figure 2: Summary stats table ──────────────────────────
    fig2, ax = plt.subplots(figsize=(10, 4))
    ax.axis("off")

    rows_data = []
    for key, (label, color) in exps.items():
        data = load(key)
        if not data:
            rows_data.append([label, "N/A","N/A","N/A","N/A","N/A"])
            continue
        lats = [d["p99"] for d in data if not np.isnan(d["p99"])]
        reps = [d["replicas"] for d in data]
        comp = slo_compliance(data)
        rows_data.append([
            label,
            f"{np.mean(lats):.3f}s" if lats else "N/A",
            f"{np.max(lats):.3f}s"  if lats else "N/A",
            f"{np.percentile(lats,99):.3f}s" if lats else "N/A",
            f"{max(reps)}",
            f"{comp:.1f}%",
        ])

    cols = ["Experiment","Avg P99","Max P99",
            "P99 of P99","Max Replicas","SLO Compliance"]
    table = ax.table(
        cellText=rows_data,
        colLabels=cols,
        cellLoc="center", loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 2.2)

    # Color header
    for j in range(len(cols)):
        table[0, j].set_facecolor("#1a237e")
        table[0, j].set_text_props(color="white", fontweight="bold")

    # Color rows
    colors_map = {"custom":"#E3F2FD","hpa70":"#FFF3E0","hpa90":"#FFEBEE"}
    for i, key in enumerate(exps.keys()):
        for j in range(len(cols)):
            table[i+1, j].set_facecolor(
                colors_map.get(key, "white"))

    fig2.suptitle(
        "Experiment Summary — Elastic ML Inference Project\n"
        "TU Ilmenau · Cloud Computing APL 2026",
        fontsize=12, fontweight="bold")
    plt.tight_layout()
    out2 = os.path.join(RESULTS_DIR, "summary_table.png")
    plt.savefig(out2, dpi=180, bbox_inches="tight")
    print(f"Saved: {out2}")
    plt.close()

    print("\n── Experiment Summary ──────────────────────────────")
    print(f"{'Experiment':<25} {'Avg P99':>8} {'SLO%':>8} {'MaxRep':>8}")
    print("─" * 55)
    for key, (label, _) in exps.items():
        data = load(key)
        if not data:
            print(f"  {label:<23} {'N/A':>8}")
            continue
        lats = [d["p99"] for d in data if not np.isnan(d["p99"])]
        reps = [d["replicas"] for d in data]
        comp = slo_compliance(data)
        avg  = np.mean(lats) if lats else 0
        print(f"  {label:<23} {avg:>7.3f}s {comp:>7.1f}% {max(reps):>7}")

if __name__ == "__main__":
    plot_all()
