#!/usr/bin/env python3
"""
Generate comparison plots from experiment CSV files.
Required by slide 17: latency time-series and CPU cores comparison.
"""

import csv
import os
import sys

# Use matplotlib without display (saves to file)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

RESULTS_DIR = os.path.dirname(os.path.abspath(__file__))
SLO_LIMIT   = 0.5  # seconds

def load_csv(name):
    path = os.path.join(RESULTS_DIR, f"{name}.csv")
    if not os.path.exists(path):
        print(f"  Missing: {path}")
        return None
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "elapsed":     float(row["elapsed"]),
                "p99_latency": float(row["p99_latency"])
                                if row["p99_latency"] != ""
                                and row["p99_latency"] != "None"
                                else None,
                "replicas":    int(row["replicas"])
                                if row["replicas"] != ""
                                else 0,
            })
    return rows

def plot_all():
    experiments = {
        "custom":  ("Custom C++ Autoscaler", "#2196F3"),
        "hpa70":   ("HPA 70% CPU Target",    "#FF9800"),
        "hpa90":   ("HPA 90% CPU Target",    "#F44336"),
    }

    fig, axes = plt.subplots(2, 1, figsize=(12, 9))
    fig.suptitle(
        "Elastic ML Inference: Custom Autoscaler vs HPA\n"
        "Technische Universität Ilmenau — Cloud Computing APL",
        fontsize=13, fontweight="bold")

    ax_lat  = axes[0]  # P99 latency
    ax_rep  = axes[1]  # Replica count (CPU cores)

    loaded_any = False
    for exp_key, (label, color) in experiments.items():
        data = load_csv(exp_key)
        if not data:
            continue
        loaded_any = True

        times = [d["elapsed"] for d in data]
        lats  = [d["p99_latency"] for d in data]
        reps  = [d["replicas"] for d in data]

        # Fill None latency gaps
        lats_clean = []
        for l in lats:
            lats_clean.append(l if l is not None else np.nan)

        ax_lat.plot(times, lats_clean,
                    label=label, color=color,
                    linewidth=2, marker="o", markersize=3)
        ax_rep.step(times, reps,
                    label=label, color=color,
                    linewidth=2, where="post")

    if not loaded_any:
        print("No CSV files found. Run experiments first.")
        return

    # Latency plot formatting
    ax_lat.axhline(y=SLO_LIMIT, color="red",
                   linestyle="--", linewidth=1.5,
                   label=f"SLO limit ({SLO_LIMIT}s)")
    ax_lat.set_ylabel("P99 Latency (seconds)", fontsize=11)
    ax_lat.set_title("P99 Request Latency Over Time", fontsize=11)
    ax_lat.legend(fontsize=9)
    ax_lat.grid(True, alpha=0.3)
    ax_lat.set_ylim(bottom=0)
    ax_lat.set_xlabel("Time (seconds)", fontsize=10)

    # Replica count plot formatting
    ax_rep.set_ylabel("Replica Count (CPU cores)", fontsize=11)
    ax_rep.set_title("Inference Replicas (CPU Cores) Over Time",
                     fontsize=11)
    ax_rep.legend(fontsize=9)
    ax_rep.grid(True, alpha=0.3)
    ax_rep.set_ylim(bottom=0)
    ax_rep.yaxis.set_major_locator(
        plt.MaxNLocator(integer=True))
    ax_rep.set_xlabel("Time (seconds)", fontsize=10)

    plt.tight_layout()
    out = os.path.join(RESULTS_DIR, "comparison.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved: {out}")
    plt.close()

if __name__ == "__main__":
    plot_all()
