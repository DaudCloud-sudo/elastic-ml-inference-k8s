#!/usr/bin/env python3
"""
Generate comparison plots from experiment CSV files.
Slide 17: p99 latency + CPU cores time-series comparison.
"""
import csv, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RESULTS_DIR = os.path.dirname(os.path.abspath(__file__))
SLO         = 0.5

def load(name):
    path = os.path.join(RESULTS_DIR, f"{name}.csv")
    if not os.path.exists(path):
        print(f"  Missing: {path}")
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
            })
    return rows

def plot():
    exps = {
        "custom": ("Custom C++ Autoscaler", "#2196F3"),
        "hpa70":  ("HPA 70% CPU Target",    "#FF9800"),
        "hpa90":  ("HPA 90% CPU Target",    "#F44336"),
    }

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9))
    fig.suptitle(
        "Elastic ML Inference — Custom Autoscaler vs Kubernetes HPA\n"
        "Technische Universität Ilmenau · Cloud Computing APL",
        fontsize=13, fontweight="bold")

    found = False
    for key, (label, color) in exps.items():
        data = load(key)
        if not data:
            continue
        found = True
        t   = [d["elapsed"]  for d in data]
        lat = [d["p99"]      for d in data]
        rep = [d["replicas"] for d in data]
        ax1.plot(t, lat, label=label, color=color,
                 linewidth=2, marker="o", markersize=4)
        ax2.step(t, rep, label=label, color=color,
                 linewidth=2, where="post")

    if not found:
        print("No CSV files found. Run experiments first.")
        return

    # P99 latency panel
    ax1.axhline(SLO, color="red", linestyle="--",
                linewidth=2, label=f"SLO = {SLO}s")
    ax1.fill_between([0, ax1.get_xlim()[1] if ax1.get_xlim()[1]>0 else 800],
                     SLO, 2, alpha=0.08, color="red")
    ax1.set_ylabel("P99 Latency (s)", fontsize=12)
    ax1.set_title("P99 Request Latency Over Time", fontsize=12)
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(bottom=0)
    ax1.set_xlabel("Time (s)", fontsize=10)

    # Replica count panel
    ax2.set_ylabel("Active Replicas (= CPU cores)", fontsize=12)
    ax2.set_title("Inference Replicas Over Time", fontsize=12)
    ax2.legend(fontsize=10)
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(bottom=0)
    ax2.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax2.set_xlabel("Time (s)", fontsize=10)

    plt.tight_layout()
    out = os.path.join(RESULTS_DIR, "comparison.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\nSaved: {out}")

if __name__ == "__main__":
    plot()
