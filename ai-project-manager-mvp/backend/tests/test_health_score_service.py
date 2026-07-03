from datetime import date

from app.services.health_score_service import calculate_project_health


def test_health_score_combines_risk_schedule_budget_milestone_and_demand():
    result = calculate_project_health(
        {"key": "p1", "budget_usage": 85, "milestone_date": "2026-05-28", "milestone_label": "评审"},
        tasks=[
            {"status": "todo", "due_date": "2026-05-20"},
            {"status": "doing", "due_date": "2026-05-30"},
            {"status": "done", "due_date": "2026-05-10"},
        ],
        risks=[
            {"status": "跟进中", "impact": "高"},
            {"status": "已解决", "impact": "高"},
        ],
        demands=[
            {"status": "待评估", "scope_impact": "重大影响"},
            {"status": "已完成", "scope_impact": "无"},
            {"status": "已纳入计划", "scope_impact": "影响排期"},
        ],
        milestones=[{"status": "待开始", "date": "2026-05-18"}],
        today=date(2026, 5, 27),
    )

    assert result["health"] == 50
    assert result["signals"]["open_risks"] == 1
    assert result["signals"]["high_risks"] == 1
    assert result["signals"]["overdue_tasks"] == 1
    assert result["signals"]["due_soon_tasks"] == 1
    assert result["signals"]["overdue_milestones"] == 1
    assert result["signals"]["due_soon_milestones"] == 1
    assert result["signals"]["open_demands"] == 1


def test_health_score_moves_when_tasks_and_risks_are_closed():
    project = {"key": "p1", "budget_usage": 0, "milestone_date": "", "milestone_label": ""}
    tasks = [{"status": "todo", "due_date": "2026-05-20"}]
    risks = [{"status": "跟进中", "impact": "高"}]

    before = calculate_project_health(
        project,
        tasks=tasks,
        risks=risks,
        demands=[],
        milestones=[],
        today=date(2026, 5, 27),
    )
    after = calculate_project_health(
        project,
        tasks=[{**tasks[0], "status": "done"}],
        risks=[{**risks[0], "status": "已解决"}],
        demands=[],
        milestones=[],
        today=date(2026, 5, 27),
    )

    assert before["health"] == 80
    assert after["health"] == 100
    assert after["health"] > before["health"]
