#!/usr/bin/env python3
"""Analyze frame-count impact on HSI transfer rate from sweep CSV."""

from __future__ import annotations

import argparse
import csv

from collections import defaultdict
from pathlib import Path


def ols(X: list[list[float]], Y: list[float]) -> tuple[list[float], float]:
    p = len(X[0])
    xtx = [[0.0] * p for _ in range(p)]
    xty = [0.0] * p
    for x, y in zip(X, Y):
        for i in range(p):
            xty[i] += x[i] * y
            for j in range(p):
                xtx[i][j] += x[i] * x[j]
    aug = [row[:] + [b] for row, b in zip(xtx, xty)]
    for col in range(p):
        pivot = max(range(col, p), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        for row in range(col + 1, p):
            factor = aug[row][col] / aug[col][col]
            for j in range(col, p + 1):
                aug[row][j] -= factor * aug[col][j]
    beta = [0.0] * p
    for i in range(p - 1, -1, -1):
        beta[i] = aug[i][p]
        for j in range(i + 1, p):
            beta[i] -= aug[i][j] * beta[j]
        beta[i] /= aug[i][i]
    ybar = sum(Y) / len(Y)
    ss_tot = sum((y - ybar) ** 2 for y in Y)
    ss_res = sum((y - sum(b * xi for b, xi in zip(beta, x))) ** 2 for x, y in zip(X, Y))
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
    return beta, r2


def load_csv(path: Path) -> list[dict]:
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    for row in rows:
        for key in (
            "total_samples",
            "record_length",
            "num_frames",
            "transfer_time_ms",
            "transfer_rate_Mbps",
            "grpc_transfer_ms",
            "grpc_publish_ms",
        ):
            row[key] = float(row[key])
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "csv",
        nargs="?",
        default=Path(__file__).resolve().parent.parent
        / "results"
        / "hsi_transfer_sweep_20260724_092506.csv",
        type=Path,
    )
    args = parser.parse_args()
    rows = load_csv(args.csv)

    by_total: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_total[int(row["total_samples"])].append(row)

    print("=== Per-total: transfer_time_ms = intercept + slope * num_frames ===")
    print(f"{'total':>12}  {'intercept_ms':>12}  {'ms/frame':>10}  {'R2':>6}")
    for total in sorted(by_total):
        pts = sorted(by_total[total], key=lambda r: r["num_frames"])
        xs = [p["num_frames"] for p in pts]
        ys = [p["transfer_time_ms"] for p in pts]
        xbar = sum(xs) / len(xs)
        ybar = sum(ys) / len(ys)
        ss_xx = sum((x - xbar) ** 2 for x in xs)
        ss_yy = sum((y - ybar) ** 2 for y in ys)
        slope = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / ss_xx
        intercept = ybar - slope * xbar
        yhat = [intercept + slope * x for x in xs]
        ss_res = sum((y - yh) ** 2 for y, yh in zip(ys, yhat))
        r2 = 1 - ss_res / ss_yy if ss_yy else float("nan")
        print(f"{total:>12,}  {intercept:>12.3f}  {slope:>10.4f}  {r2:>6.3f}")

    print("\n=== Per-total: transfer_rate_Mbps vs num_frames ===")
    for total in sorted(by_total):
        pts = sorted(by_total[total], key=lambda r: r["num_frames"])
        low, high = pts[0], pts[-1]
        drop = (
            100
            * (low["transfer_rate_Mbps"] - high["transfer_rate_Mbps"])
            / low["transfer_rate_Mbps"]
        )
        print(
            f"{total:>12,}: {low['transfer_rate_Mbps']:>7.1f} Mbps @ {int(low['num_frames']):>5,} frames  ->  "
            f"{high['transfer_rate_Mbps']:>7.1f} Mbps @ {int(high['num_frames']):>5,} frames  "
            f"({drop:.0f}% slower effective rate)"
        )

    print("\n=== Global additive model ===")
    print("transfer_time_ms = a * payload_Mbit + b * num_frames + c")
    X = []
    Y = []
    for row in rows:
        payload_mbit = row["total_samples"] * 8 / 1e6
        X.append([payload_mbit, row["num_frames"], 1.0])
        Y.append(row["transfer_time_ms"])
    beta, r2 = ols(X, Y)
    a, b, c = beta
    bulk_mbps = 1000 / a if a else float("inf")
    print(f"  a (payload)  = {a:.4f} ms/Mbit   -> bulk ~ {bulk_mbps:.0f} Mbps")
    print(f"  b (frames)   = {b:.6f} ms/frame -> {b * 1000:.1f} us/frame")
    print(f"  c (fixed)    = {c:.3f} ms")
    print(f"  R2           = {r2:.4f}")

    print("\n=== gRPC transfer only (same model) ===")
    Yg = [row["grpc_transfer_ms"] for row in rows]
    beta_g, r2_g = ols(X, Yg)
    print(f"  a = {beta_g[0]:.4f} ms/Mbit -> {1000 / beta_g[0]:.0f} Mbps wire rate")
    print(f"  b = {beta_g[1]:.6f} ms/frame -> {beta_g[1] * 1000:.1f} us/frame")
    print(f"  c = {beta_g[2]:.3f} ms")
    print(f"  R2 = {r2_g:.4f}")

    print("\n=== Rate model (derived) ===")
    print(
        "rate_Mbps = 8000 * total_samples / (a*8*total_samples/1e6 + b*num_frames + c) / 1e6 * 1000"
    )
    print("          = payload_Mbit / (a*payload_Mbit + b*num_frames + c) * 1000")
    print("\nPredictions:")
    print(f"{'total':>12}  {'frames':>8}  {'meas Mbps':>10}  {'pred Mbps':>10}")
    for row in rows:
        payload_mbit = row["total_samples"] * 8 / 1e6
        t_pred = a * payload_mbit + b * row["num_frames"] + c
        rate_pred = payload_mbit / t_pred * 1000
        print(
            f"{int(row['total_samples']):>12,}  {int(row['num_frames']):>8,}  "
            f"{row['transfer_rate_Mbps']:>10.1f}  {rate_pred:>10.1f}"
        )

    print("\n=== Frame overhead share at each total ===")
    for total in sorted(by_total):
        payload_mbit = total * 8 / 1e6
        pts = sorted(by_total[total], key=lambda r: r["num_frames"])
        for pt in pts:
            nf = pt["num_frames"]
            payload_ms = a * payload_mbit
            frame_ms = b * nf
            fixed_ms = c
            total_ms = payload_ms + frame_ms + fixed_ms
            frame_pct = 100 * frame_ms / total_ms
            print(
                f"total={total:>12,} frames={int(nf):>6,}: "
                f"frame overhead {frame_pct:5.1f}% of predicted time "
                f"({frame_ms:.2f} ms of {total_ms:.2f} ms)"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
