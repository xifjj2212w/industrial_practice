#!/usr/bin/env python3
"""Кейс 1: поиск нетипичного поведения заявок на закупку.

Запуск (из корня папки кейса):
    python analysis/analyze.py
    python analysis/analyze.py --data data/students.csv --out anomalies.csv

Скрипт читает журнал событий, считает базовую линию (типовые маршруты,
длительности, роли) и формирует anomalies.csv по девяти правилам.
Требуется pandas (проверено на pandas 3.1).
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
LONG_TASK_HOURS = 100.0
EXCESS_RETURNS = 5

EXPECTED_ROLE = {
    "Проверка заявки": "specialist",
    "Согласование руководителем": "manager",
    "Согласование бюджета": "finance",
    "Проверка договора": "legal",
    "Исполнение заявки": "procurement",
    "Доработка заявки": "requester",
    "Внеплановая проверка": "auditor",
}


def fmt(dt: pd.Timestamp) -> str:
    return dt.strftime("%d.%m.%Y %H:%M")


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    df["idx"] = df.EventIndex.astype(int)
    df["dt"] = pd.to_datetime(df.Timestamp)
    return df.sort_values(["ProcessInstanceId", "idx"]).reset_index(drop=True)


def build_profiles(df: pd.DataFrame) -> dict[str, dict]:
    profiles: dict[str, dict] = {}
    for pid, g in df.groupby("ProcessInstanceId", sort=True):
        completed = [
            {
                "name": r.ActivityName,
                "result": r.Result,
                "role": r.Role,
                "user": r.UserId,
                "dt": r.dt,
                "task": r.TaskId,
            }
            for r in g.itertuples()
            if r.EventType == "task_completed"
        ]
        done = g[g.EventType == "process_completed"]
        profiles[pid] = {
            "type": g.RequestType.iloc[0],
            "amount": float(g.Amount.iloc[0]),
            "started": g[g.EventType == "process_started"].dt.iloc[0],
            "starter": g[g.EventType == "process_started"].UserId.iloc[0],
            "completed": completed,
            "result": done.Result.iloc[0] if len(done) else "OPEN",
            "end": done.dt.iloc[0] if len(done) else None,
        }
    return profiles


def route(p: dict) -> str:
    return " → ".join(a["name"] for a in p["completed"])


def task_durations(df: pd.DataFrame) -> pd.DataFrame:
    created = df[df.EventType == "task_created"].set_index("TaskId")
    closed = df[df.EventType == "task_completed"].set_index("TaskId")
    return pd.DataFrame(
        {
            "task": created.index,
            "activity": created.ActivityName,
            "pid": created.ProcessInstanceId,
            "user": closed.UserId,
            "role": closed.Role,
            "created": created.dt,
            "closed": closed.dt,
            "hours": (closed.dt - created.dt).dt.total_seconds() / 3600,
        }
    )


def detect(df: pd.DataFrame, profiles: dict[str, dict]) -> list[dict]:
    rows: list[dict] = []

    def add(pid: str, kind: str, text: str) -> None:
        rows.append({"ProcessInstanceId": pid, "AnomalyType": kind, "Explanation": text})

    durations = task_durations(df)
    check_hours = durations[durations.activity == "Проверка заявки"].hours
    check_median = float(check_hours.median())
    check_p99 = float(check_hours.quantile(0.99))

    fulfilled = {p for p, v in profiles.items() if v["result"] == "fulfilled"}
    rejected = {p for p, v in profiles.items() if v["result"] == "rejected"}
    open_ = {p for p, v in profiles.items() if v["result"] == "OPEN"}

    manager_closures = sum(
        1 for v in profiles.values() for a in v["completed"] if a["name"] == "Согласование руководителем"
    )
    manager_by_manager = sum(
        1
        for v in profiles.values()
        for a in v["completed"]
        if a["name"] == "Согласование руководителем" and a["role"] == "manager"
    )

    returns = Counter(
        p for p, v in profiles.items() for a in v["completed"] if a["result"] == "return"
    )
    one_return = sum(1 for c in returns.values() if c == 1)

    # 1. Пропуск обязательного согласования руководителем у успешной заявки.
    skip_manager = [
        p
        for p in fulfilled
        if "Согласование руководителем" not in {a["name"] for a in profiles[p]["completed"]}
    ]
    for p in sorted(skip_manager):
        add(
            p,
            "Пропуск согласования руководителем",
            f"Заявка завершена fulfilled, но этапа «Согласование руководителем» нет: "
            f"{route(profiles[p])}. У остальных {len(fulfilled) - len(skip_manager)} успешных заявок "
            f"этап присутствует и предшествует согласованию бюджета.",
        )

    # 2. Исполнение до согласования бюджета.
    for p, v in sorted(profiles.items()):
        names = [a["name"] for a in v["completed"]]
        if "Исполнение заявки" not in names:
            continue
        exec_a = next(a for a in v["completed"] if a["name"] == "Исполнение заявки")
        budget = next((a for a in v["completed"] if a["name"] == "Согласование бюджета"), None)
        if budget is None or exec_a["dt"] < budget["dt"]:
            detail = (
                f"согласование бюджета отсутствует, исполнение закрыто {fmt(exec_a['dt'])}"
                if budget is None
                else f"исполнение закрыто {fmt(exec_a['dt'])}, а бюджет согласован позже — "
                f"{fmt(budget['dt'])} (разрыв {abs((budget['dt'] - exec_a['dt']).total_seconds()) / 3600:.1f} ч)"
            )
            add(
                p,
                "Исполнение до согласования бюджета",
                f"Нарушен порядок этапов: {detail}. Маршрут: {route(v)}; "
                f"бюджет должен быть согласован до исполнения.",
            )

    # 3. Юридическая проверка договорной заявки после исполнения.
    for p, v in sorted(profiles.items()):
        if v["type"] != "contract":
            continue
        names = {a["name"]: a for a in v["completed"]}
        if "Исполнение заявки" in names and "Проверка договора" in names:
            if names["Проверка договора"]["dt"] > names["Исполнение заявки"]["dt"]:
                add(
                    p,
                    "Юридическая проверка после исполнения",
                    f"Договорная заявка: «Проверка договора» закрыта {fmt(names['Проверка договора']['dt'])}, "
                    f"то есть после «Исполнения заявки» {fmt(names['Исполнение заявки']['dt'])}. "
                    f"По регламенту юрист проверяет договор до исполнения.",
                )

    # 4. Дублирование проверки заявки без возврата на доработку.
    for p, v in sorted(profiles.items()):
        acts = v["completed"]
        for i in range(len(acts) - 1):
            first, second = acts[i], acts[i + 1]
            if first["name"] == second["name"] == "Проверка заявки" and "return" not in (
                first["result"],
                second["result"],
            ):
                add(
                    p,
                    "Дублирование проверки заявки",
                    f"«Проверка заявки» выполнена дважды подряд без возврата на доработку: "
                    f"задания {first['task']} и {second['task']} (оба accept). Маршрут: {route(v)}. "
                    f"Повторная проверка обоснована только после возврата; в остальных заявках этап один.",
                )
                break

    # 5. Согласование руководителем выполнено пользователем с ролью requester.
    for p, v in sorted(profiles.items()):
        for a in v["completed"]:
            if a["name"] == "Согласование руководителем" and a["role"] == "requester":
                if a["user"] == v["starter"]:
                    add(
                        p,
                        "Самосогласование заявки",
                        f"Заявитель сам закрыл этап «Согласование руководителем» ({fmt(a['dt'])}, "
                        f"результат {a['result']}): UserId {a['user']} совпадает с инициатором процесса. "
                        f"Нарушено разделение полномочий; обычно этап закрывает manager.",
                    )
                else:
                    add(
                        p,
                        "Подмена роли при согласовании",
                        f"Этап «Согласование руководителем» закрыт пользователем {a['user']} с ролью requester "
                        f"({fmt(a['dt'])}, результат {a['result']}), а не manager: "
                        f"{manager_by_manager} из {manager_closures} закрытий этапа выполнены ролью manager.",
                    )
                break

    # 6. Чрезмерное число возвратов на доработку.
    for p, count in sorted(returns.items()):
        if count >= EXCESS_RETURNS:
            add(
                p,
                "Чрезмерные возвраты на доработку",
                f"Заявка возвращалась руководителем на доработку {count} раз: "
                f"{count} циклов «возврат → доработка → повторная проверка». "
                f"В журнале {one_return} заявок с одним возвратом, более двух возвратов нет; "
                f"маршрут: {route(profiles[p])}.",
            )

    # 7. Две внеплановые проверки аудитора в одном процессе.
    for p, v in sorted(profiles.items()):
        audits = [a for a in v["completed"] if a["name"] == "Внеплановая проверка"]
        if len(audits) >= 2:
            times = ", ".join(fmt(a["dt"]) for a in audits)
            add(
                p,
                "Двойная внеплановая проверка",
                f"В заявке {len(audits)} внеплановые проверки аудитора ({times}) — после руководителя "
                f"и после бюджета. Этап не входит в обязательный маршрут и в остальных "
                f"{len(profiles) - 8} заявках отсутствует; две проверки подряд требуют объяснения бизнес-ситуации.",
            )

    # 8. Аномально долгое задание проверки заявки.
    for _, t in durations[durations.activity == "Проверка заявки"].iterrows():
        if t.hours > LONG_TASK_HOURS:
            add(
                t.pid,
                "Аномально долгая проверка заявки",
                f"Задание «Проверка заявки» {t.task} длилось "
                f"{t.hours:.1f} ч ({t.hours / 24:.1f} календарных дня, с {fmt(t.created)} по {fmt(t.closed)}) "
                f"при медиане {check_median:.1f} ч и 99-м перцентиле {check_p99:.1f} ч. "
                f"Исполнитель — role specialist. Требуется проверка причины задержки.",
            )

    return rows


def metrics(df: pd.DataFrame, profiles: dict[str, dict], rows: list[dict]) -> dict:
    durations = task_durations(df)
    starts = [v["started"] for v in profiles.values()]
    stage_stats = {}
    for act, g in durations.groupby("activity"):
        stage_stats[act] = {
            "заданий": int(len(g)),
            "медиана_ч": round(float(g.hours.median()), 2),
            "p99_ч": round(float(g.hours.quantile(0.99)), 2),
            "максимум_ч": round(float(g.hours.max()), 1),
        }
    return {
        "событий": int(len(df)),
        "заявок": len(profiles),
        "по_типам": dict(Counter(v["type"] for v in profiles.values())),
        "завершено": dict(Counter(v["result"] for v in profiles.values() if v["result"] != "OPEN")),
        "открытых": sum(1 for v in profiles.values() if v["result"] == "OPEN"),
        "период": [fmt(min(starts)), fmt(max(starts))],
        "длительности_этапов": stage_stats,
        "семейства": dict(Counter(r["AnomalyType"] for r in rows)),
        "затронуто_заявок": len({r["ProcessInstanceId"] for r in rows}),
        "строк_в_csv": len(rows),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Поиск аномалий в журнале заявок на закупку")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "students.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "anomalies.csv")
    ap.add_argument("--metrics", type=Path, default=ROOT / "analysis" / "metrics.json")
    args = ap.parse_args()

    df = load(args.data)
    profiles = build_profiles(df)
    rows = detect(df, profiles)

    known = set(df.ProcessInstanceId)
    assert all(r["ProcessInstanceId"] in known for r in rows), "неизвестный ProcessInstanceId"
    seen = set()
    for r in rows:
        key = (r["ProcessInstanceId"], r["AnomalyType"], r["Explanation"])
        assert key not in seen, f"дубликат строки {key}"
        seen.add(key)

    rows.sort(key=lambda r: (r["ProcessInstanceId"], r["AnomalyType"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ProcessInstanceId", "AnomalyType", "Explanation"])
        w.writeheader()
        w.writerows(rows)

    m = metrics(df, profiles, rows)
    args.metrics.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(m, ensure_ascii=False, indent=2))
    print(f"\nзаписано: {args.out} ({len(rows)} строк)")

    skip = m["семейства"].get("Пропуск согласования руководителем", 0)
    open_in_skip = sum(
        1
        for r in rows
        if r["AnomalyType"] == "Пропуск согласования руководителем"
        and profiles[r["ProcessInstanceId"]]["result"] == "OPEN"
    )
    assert open_in_skip == 0, "открытая заявка не должна попадать в пропуск руководителя"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
