from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from typing import Any


CLOSED_STATUSES = {"done", "已完成", "已关闭", "已解决", "已取消", "已拒绝", "已纳入计划"}


def clamp(value: int, minimum: int = 0, maximum: int = 100) -> int:
    return max(minimum, min(maximum, value))


def row_to_plain(row: Any) -> dict:
    return dict(row)


def parse_date(value: str, today: date | None = None) -> date | None:
    today = today or date.today()
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    match = re.search(r"(\d{1,2})[-/.月](\d{1,2})", text)
    if match:
        return date(today.year, int(match.group(1)), int(match.group(2)))
    return None


def is_open_status(status: str) -> bool:
    return str(status or "").strip() not in CLOSED_STATUSES


def risk_penalty(risks: list[dict]) -> tuple[int, int, int]:
    open_risks = [risk for risk in risks if is_open_status(risk.get("status", ""))]
    penalty = 0
    high_count = 0
    for risk in open_risks:
        impact = str(risk.get("impact") or "")
        if impact == "高":
            high_count += 1
            penalty += 12
        elif impact == "中":
            penalty += 7
        elif impact == "低":
            penalty += 4
        else:
            penalty += 6
    return min(penalty, 35), len(open_risks), high_count


def task_penalty(tasks: list[dict], today: date) -> tuple[int, int, int]:
    overdue = 0
    due_soon = 0
    for task in tasks:
        if not is_open_status(task.get("status", "")):
            continue
        due_date = parse_date(task.get("due_date", ""), today)
        if not due_date:
            continue
        if due_date < today:
            overdue += 1
        elif due_date <= today + timedelta(days=7):
            due_soon += 1
    penalty = min(overdue * 8, 24) + min(due_soon * 3, 9)
    return penalty, overdue, due_soon


def budget_penalty(project: dict) -> int:
    usage = int(project.get("budget_usage") or 0)
    if usage > 100:
        return 20
    if usage >= 90:
        return 14
    if usage >= 80:
        return 8
    if usage >= 70:
        return 4
    return 0


def milestone_penalty(project: dict, milestones: list[dict], today: date) -> tuple[int, int, int]:
    items = list(milestones)
    if project.get("milestone_date") or project.get("milestone_label"):
        items.append(
            {
                "title": project.get("milestone_label", ""),
                "date": project.get("milestone_date", ""),
                "status": "",
            }
        )

    overdue = 0
    due_soon = 0
    for milestone in items:
        if not is_open_status(milestone.get("status", "")):
            continue
        target_date = parse_date(milestone.get("date", ""), today)
        if not target_date:
            continue
        if target_date < today:
            overdue += 1
        elif target_date <= today + timedelta(days=14):
            due_soon += 1
    penalty = min(overdue * 10, 20) + min(due_soon * 4, 8)
    return penalty, overdue, due_soon


def demand_penalty(demands: list[dict]) -> tuple[int, int]:
    open_demands = [demand for demand in demands if is_open_status(demand.get("status", ""))]
    penalty = 0
    for demand in open_demands:
        scope = str(demand.get("scope_impact") or "")
        penalty += 5 if any(keyword in scope for keyword in ("重大", "高", "影响")) else 3
    return min(penalty, 15), len(open_demands)


def calculate_project_health(
    project: dict,
    tasks: list[dict],
    risks: list[dict],
    demands: list[dict],
    milestones: list[dict],
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    risk_score, open_risks, high_risks = risk_penalty(risks)
    schedule_score, overdue_tasks, due_soon_tasks = task_penalty(tasks, today)
    budget_score = budget_penalty(project)
    milestone_score, overdue_milestones, due_soon_milestones = milestone_penalty(project, milestones, today)
    demand_score, open_demands = demand_penalty(demands)

    total_penalty = risk_score + schedule_score + budget_score + milestone_score + demand_score
    return {
        "health": clamp(100 - total_penalty),
        "penalties": {
            "risk": risk_score,
            "schedule": schedule_score,
            "budget": budget_score,
            "milestone": milestone_score,
            "demand": demand_score,
            "total": total_penalty,
        },
        "signals": {
            "open_risks": open_risks,
            "high_risks": high_risks,
            "overdue_tasks": overdue_tasks,
            "due_soon_tasks": due_soon_tasks,
            "overdue_milestones": overdue_milestones,
            "due_soon_milestones": due_soon_milestones,
            "open_demands": open_demands,
        },
    }


def calculate_project_health_from_db(connection, project: dict) -> dict[str, Any]:
    key = project["key"]
    tasks = [
        row_to_plain(row)
        for row in connection.execute("select * from tasks where project_key = ?", [key]).fetchall()
    ]
    risks = [
        row_to_plain(row)
        for row in connection.execute("select * from risks where project_key = ?", [key]).fetchall()
    ]
    demands = [
        row_to_plain(row)
        for row in connection.execute("select * from demands where project_key = ?", [key]).fetchall()
    ]
    milestones = [
        row_to_plain(row)
        for row in connection.execute("select * from milestones where project_key = ?", [key]).fetchall()
    ]
    return calculate_project_health(project, tasks, risks, demands, milestones)
