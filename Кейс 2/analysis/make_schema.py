#!/usr/bin/env python3
"""Рисует схему восстановленного процесса по данным Кейса 2.

Запуск:
    python analysis/make_schema.py
Результат:
    schema/process_schema.png  — схема для отчёта
    schema/process_schema.mmd  — та же схема в Mermaid (редактируемый исходник)
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "schema"

plt.rcParams["font.family"] = "DejaVu Sans"

HUMAN = "#DCE9F7"
SYSTEM = "#EEF1F5"
GREEN = "#DFF0D8"
RED = "#F8D7DA"
ORANGE = "#FFE8CC"
EDGE = "#2F4A66"


def box(ax, x, y, w, h, title, role, fill):
    ax.add_patch(
        FancyBboxPatch(
            (x - w / 2, y - h / 2),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.12",
            linewidth=1.4,
            edgecolor=EDGE,
            facecolor=fill,
            zorder=2,
        )
    )
    ax.text(x, y + 0.13, title, ha="center", va="center", fontsize=9.2, fontweight="bold", zorder=3)
    ax.text(x, y - 0.22, role, ha="center", va="center", fontsize=7.6, color="#44546A", style="italic", zorder=3)


def arrow(ax, p1, p2, rad=0.0, label=None, lx=0.0, ly=0.0):
    ax.add_patch(
        FancyArrowPatch(
            p1,
            p2,
            arrowstyle="-|>",
            mutation_scale=13,
            linewidth=1.4,
            color=EDGE,
            connectionstyle=f"arc3,rad={rad}",
            shrinkA=2,
            shrinkB=2,
            zorder=1,
        )
    )
    if label:
        ax.text(
            (p1[0] + p2[0]) / 2 + lx,
            (p1[1] + p2[1]) / 2 + ly,
            label,
            ha="center",
            va="center",
            fontsize=8.2,
            color="#1F3552",
            bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor="none"),
            zorder=4,
        )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(19, 9.6))
    ax.set_xlim(-0.2, 19.2)
    ax.set_ylim(-0.4, 10.4)
    ax.axis("off")

    ax.text(0.2, 10.15, "Восстановленная схема процесса заявки на закупку", fontsize=15, fontweight="bold", color="#1F3552")
    ax.text(0.2, 9.75, "1000 экземпляров, 6508 событий. Числа на стрелках — сколько раз наблюдался переход.", fontsize=9.5, color="#44546A")

    # координаты основного ряда
    y = 5.2
    nodes = {
        "reg": (2.0, "Регистрация заявки", "system", SYSTEM, 2.6),
        "check": (4.9, "Первичная проверка", "specialist", HUMAN, 2.6),
        "mgr": (8.1, "Согласование\nруководителем", "manager", HUMAN, 3.0),
        "budget": (11.2, "Проверка бюджета", "finance", HUMAN, 2.6),
        "exec": (14.3, "Исполнение закупки", "procurement", HUMAN, 2.8),
        "done": (17.3, "Заявка выполнена", "конец", GREEN, 2.6),
    }
    for _, (x, title, role, fill, w) in nodes.items():
        box(ax, x, y, w, 0.95, title, role, fill)

    # дополнительные узлы
    box(ax, 8.1, 8.0, 2.5, 0.9, "Доработка заявки", "requester", HUMAN)
    box(ax, 12.0, 8.0, 3.1, 0.9, "Дополнительное\nсогласование", "director", HUMAN)
    box(ax, 6.7, 2.2, 2.6, 0.9, "Заявка отклонена", "конец", RED)
    box(ax, 10.8, 2.2, 2.6, 0.9, "Заявка отменена", "конец", ORANGE)

    ax.add_patch(Circle((0.45, y), 0.2, facecolor="#44546A", edgecolor=EDGE, zorder=2))
    ax.text(0.45, y - 0.42, "старт", ha="center", fontsize=8.5, color="#44546A")

    # старт и основной поток
    arrow(ax, (0.65, y), (0.7, y))
    arrow(ax, (3.3, y), (3.6, y))
    arrow(ax, (6.2, y), (6.6, y), label="accept 1129", ly=0.28)
    arrow(ax, (9.6, y), (9.9, y), label="accept 911", ly=0.28)
    arrow(ax, (12.5, y), (12.9, y), label="702", ly=0.28)
    arrow(ax, (15.7, y), (16.0, y), label="911", ly=0.28)

    # отказ после проверки
    arrow(ax, (4.7, y - 0.5), (6.3, 2.65), rad=-0.12, label="reject 45", lx=-0.55, ly=0.1)
    # отказ и отмена после руководителя
    arrow(ax, (7.7, y - 0.5), (7.1, 2.65), rad=0.12, label="reject 18", lx=-0.95, ly=0.05)
    arrow(ax, (8.7, y - 0.5), (10.5, 2.65), rad=-0.12, label="cancel 26", lx=0.35, ly=-0.55)

    # возврат на доработку
    arrow(ax, (8.1, y + 0.5), (8.1, 7.55), label="return 174", lx=0.95, ly=0.0)
    arrow(ax, (6.85, 7.9), (5.0, y + 0.5), rad=0.22, label="174", lx=-0.85, ly=0.25)

    # дополнительное согласование
    arrow(ax, (11.3, y + 0.5), (11.85, 7.55), rad=-0.1, label="сумма ≥ 150 тыс.\n209", lx=-0.55, ly=-0.25)
    arrow(ax, (12.15, 7.55), (13.9, y + 0.5), rad=-0.1, label="209", lx=0.55, ly=-0.15)

    ax.text(
        0.2,
        0.55,
        "Прямоугольник — действие, подпись — роль исполнителя. Круг — старт, цветные блоки — концы процесса.\n"
        "Условие «сумма ≥ 150 тыс.» — гипотеза по данным: доп. согласование встречается только при сумме от 150 614,59,\n"
        "но 18 из 227 крупных заявок прошли без него, поэтому порог не является жёстким правилом.",
        fontsize=8.6,
        color="#44546A",
        va="bottom",
    )

    fig.tight_layout()
    path = OUT / "process_schema.png"
    fig.savefig(path, dpi=170, facecolor="white", bbox_inches="tight")
    plt.close(fig)

    (OUT / "process_schema.mmd").write_text(
        """flowchart LR
  S((старт)) --> R[Регистрация заявки<br/><i>system</i>]
  R --> P[Первичная проверка<br/><i>specialist</i>]
  P -->|accept 1129| M[Согласование руководителем<br/><i>manager</i>]
  P -->|reject 45| RJ[Заявка отклонена]
  M -->|accept 911| B[Проверка бюджета<br/><i>finance</i>]
  M -->|return 174| D[Доработка заявки<br/><i>requester</i>]
  M -->|reject 18| RJ
  M -->|cancel 26| CN[Заявка отменена]
  D -->|174| P
  B -->|702| E[Исполнение закупки<br/><i>procurement</i>]
  B -->|сумма >= 150 тыс., 209| A[Дополнительное согласование<br/><i>director</i>]
  A -->|209| E
  E -->|911| F[Заявка выполнена]
""",
        encoding="utf-8",
    )
    print(f"схема: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
