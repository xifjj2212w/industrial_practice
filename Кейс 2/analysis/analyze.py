#!/usr/bin/env python3
"""Кейс 2: восстановление процесса по журналу событий.

Запуск из корня папки кейса:
    python analysis/analyze.py

Скрипт группирует события по ProcessInstanceId, восстанавливает полные
маршруты, считает варианты, переходы и частоты и пишет:
    variants.csv     — таблица полных вариантов (Variant,Route,NumberOfCases,Share)
    transitions.csv  — пары непосредственно следующих активностей
    analysis/metrics.json — все числа, использованные в отчёте
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
END_EVENTS = {"Заявка выполнена", "Заявка отклонена", "Заявка отменена"}


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    df["idx"] = df.EventIndex.astype(int)
    df["dt"] = pd.to_datetime(df.Timestamp)
    df["amount"] = df.Amount.astype(float)
    return df.sort_values(["ProcessInstanceId", "idx"]).reset_index(drop=True)


def process_routes(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for pid, g in df.groupby("ProcessInstanceId", sort=True):
        rows.append(
            {
                "pid": pid,
                "route": tuple(g.ActivityName),
                "amount": g.amount.iloc[0],
                "start": g.dt.iloc[0],
                "end": g.dt.iloc[-1],
                "outcome": g[g.EventType == "process_completed"].Result.iloc[0],
            }
        )
    return pd.DataFrame(rows).set_index("pid")


def gap_stats(df: pd.DataFrame) -> dict:
    gaps = df.groupby("ProcessInstanceId").dt.diff().dt.total_seconds() / 3600
    out = {}
    for act, series in gaps.groupby(df.ActivityName):
        s = series.dropna()
        out[act] = {
            "наблюдений": int(len(s)),
            "медиана_ч": round(float(s.median()), 1),
            "p90_ч": round(float(s.quantile(0.9)), 1),
            "максимум_ч": round(float(s.max()), 1),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Восстановление процесса по журналу")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "students.csv")
    ap.add_argument("--outdir", type=Path, default=ROOT)
    ap.add_argument("--metrics", type=Path, default=ROOT / "analysis" / "metrics.json")
    args = ap.parse_args()

    df = load(args.data)
    procs = process_routes(df)

    # --- варианты ---
    counts = Counter(procs.route)
    variants = [
        (route, n)
        for route, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    total = len(procs)
    rows = []
    for i, (route, n) in enumerate(variants, start=1):
        rows.append(
            {
                "Variant": f"V{i}",
                "Route": " > ".join(route),
                "NumberOfCases": n,
                "Share": round(n / total, 4),
            }
        )
    args.outdir.mkdir(parents=True, exist_ok=True)
    with (args.outdir / "variants.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Variant", "Route", "NumberOfCases", "Share"])
        w.writeheader()
        w.writerows(rows)

    # --- переходы ---
    pairs = Counter()
    for route in procs.route:
        pairs.update(zip(route, route[1:]))
    with (args.outdir / "transitions.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["SourceActivity", "TargetActivity"])
        for source, target in sorted(pairs):
            w.writerow([source, target])

    # --- частоты и проверки ---
    tasks = df[df.EventType == "task_completed"]
    by_activity_result = {
        act: {res: int(n) for res, n in sub.Result.value_counts().items()}
        for act, sub in tasks.groupby("ActivityName")
    }
    coverage = {
        "старт": int((df.EventType == "process_started").sum()),
        "финиш": int((df.EventType == "process_completed").sum()),
        "заданий": int(len(tasks)),
        "активностей": int(df.ActivityName.nunique()),
        "переходов": int(len(pairs)),
        "вариантов": int(len(variants)),
    }
    assert coverage["старт"] == coverage["финиш"] == total == 1000
    assert all(p[0] == "Регистрация заявки" for p in procs.route)
    assert all(p[-1] in END_EVENTS for p in procs.route)
    assert sum(r["NumberOfCases"] for r in rows) == total

    # дополнительное согласование: только крупные суммы
    add_pids = set(df.loc[df.ActivityName == "Дополнительное согласование", "ProcessInstanceId"])
    add_amounts = procs.loc[list(add_pids), "amount"]
    add_min = float(add_amounts.min())
    large = procs[procs.amount >= add_min]
    large_without = large[~large.index.isin(add_pids)]

    cycle = (procs.end - procs.start).dt.total_seconds() / 3600
    returns = tasks[tasks.Result == "return"].groupby("ProcessInstanceId").size()

    metrics = {
        "событий": int(len(df)),
        "экземпляров": total,
        "период": [df.dt.min().strftime("%d.%m.%Y"), df.dt.max().strftime("%d.%m.%Y")],
        "покрытие": coverage,
        "результаты_процессов": dict(Counter(procs.outcome)),
        "активность_результат": by_activity_result,
        "частые_переходы": {f"{s} > {t}": n for (s, t), n in pairs.most_common()},
        "возвраты": {
            "всего": int((tasks.Result == "return").sum()),
            "заявок_с_возвратом": int(len(returns)),
            "распределение": {str(k): int(v) for k, v in returns.value_counts().sort_index().items()},
        },
        "доп_согласование": {
            "заявок": int(len(add_pids)),
            "минимальная_сумма": round(add_min, 2),
            "крупных_заявок_от_этой_суммы": int(len(large)),
            "крупных_без_доп_согласования": int(len(large_without)),
            "доля_крупных_с_согласованием": round(len(add_pids) / len(large), 3),
        },
        "цикл_ч": {
            "медиана": round(float(cycle.median()), 1),
            "p90": round(float(cycle.quantile(0.9)), 1),
            "максимум": round(float(cycle.max()), 1),
        },
        "интервалы_до_активности_ч": gap_stats(df),
        "варианты": [
            {"variant": r["Variant"], "cases": r["NumberOfCases"], "share": r["Share"], "route": r["Route"]}
            for r in rows
        ],
        "переходы": [
            {"source": s, "target": t, "count": n} for (s, t), n in sorted(pairs.items())
        ],
    }
    args.metrics.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: metrics[k] for k in ("событий", "экземпляров", "покрытие", "результаты_процессов", "доп_согласование", "цикл_ч")}, ensure_ascii=False, indent=2))
    print("\nварианты:")
    for r in rows:
        print(r["Variant"], r["NumberOfCases"], r["Share"], r["Route"])
    print(f"\nзаписано: variants.csv ({len(rows)}), transitions.csv ({len(pairs)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
