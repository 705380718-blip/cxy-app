from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException

from app.db import get_connection, init_db, row_to_dict
from app.schemas import GanttRowsPayload, ProjectCreate, ProjectUpdate
from app.services.health_score_service import calculate_project_health_from_db


router = APIRouter(prefix="/projects", tags=["projects"])


PROJECT_COLUMNS = [
    "key",
    "name",
    "customer",
    "phase",
    "status",
    "contract_status",
    "region",
    "area",
    "project_type",
    "progress",
    "days",
    "tasks",
    "risks",
    "budget_usage",
    "new_demands",
    "health",
    "budget",
    "incurred_cost",
    "payment_2025",
    "manager",
    "delivery",
    "sales",
    "start_date",
    "pre_start_date",
    "acceptance",
    "end_date",
    "spm",
    "contract_no",
    "background",
    "plan",
    "remark",
    "dashboard",
    "milestone_date",
    "milestone_label",
]


def parse_money_amount(value: str) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text or text in {"-", "待定"}:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    amount = float(match.group(1))
    if "亿" in text:
        return amount * 100_000_000
    if "万" in text:
        return amount * 10_000
    return amount


def apply_budget_usage(payload: dict) -> dict:
    budget = parse_money_amount(payload.get("budget", ""))
    incurred_cost = parse_money_amount(payload.get("incurred_cost", ""))
    if budget and incurred_cost is not None:
        payload["budget_usage"] = max(0, round((incurred_cost / budget) * 100))
    return payload


def normalize_project(row: dict) -> dict:
    row["dashboard"] = bool(row["dashboard"])
    return row


def apply_project_metrics(project: dict, connection) -> dict:
    key = project["key"]
    task_row = connection.execute(
        """
        select count(*) as task_count, avg(progress) as avg_progress
        from tasks
        where project_key = ?
        """,
        [key],
    ).fetchone()
    risk_row = connection.execute(
        """
        select count(*) as risk_count,
               sum(case when impact = '高' then 1 else 0 end) as high_count
        from risks
        where project_key = ? and status not in ('已关闭', '已解决')
        """,
        [key],
    ).fetchone()
    demand_row = connection.execute(
        "select count(*) as demand_count from demands where project_key = ?",
        [key],
    ).fetchone()
    metrics = {
        "tasks": task_row["task_count"] or 0,
        "progress": round(task_row["avg_progress"] or project["progress"] or 0),
        "risks": risk_row["risk_count"] or 0,
        "new_demands": demand_row["demand_count"] or 0,
    }
    health_payload = calculate_project_health_from_db(connection, project)
    metrics["health"] = health_payload["health"]
    metrics["health_breakdown"] = health_payload
    project.update(metrics)
    return project


def make_project_key(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()
    return slug or "project"


@router.get("")
def list_projects(search: str = "", dashboard: bool | None = None) -> list[dict]:
    init_db()
    where: list[str] = []
    params: list[str | int] = []
    if search:
        where.append("(name like ? or customer like ? or region like ? or manager like ?)")
        keyword = f"%{search}%"
        params.extend([keyword, keyword, keyword, keyword])
    if dashboard is not None:
        where.append("dashboard = ?")
        params.append(1 if dashboard else 0)
    sql = "select * from projects"
    if where:
        sql += " where " + " and ".join(where)
    sql += " order by dashboard desc, key asc"
    with get_connection() as connection:
        rows = connection.execute(sql, params).fetchall()
        return [
            normalize_project(apply_project_metrics(row_to_dict(row), connection))
            for row in rows
        ]


@router.get("/summary")
def project_summary() -> dict:
    init_db()
    with get_connection() as connection:
        project_row = connection.execute(
            """
            select
              count(*) as total,
              sum(case when dashboard = 1 then 1 else 0 end) as dashboard_count,
              avg(progress) as avg_progress
            from projects
            """
        ).fetchone()
        task_row = connection.execute(
            """
            select count(*) as task_count, avg(t.progress) as avg_task_progress
            from tasks t
            join projects p on p.key = t.project_key
            """
        ).fetchone()
        risk_row = connection.execute(
            """
            select count(*) as risk_count
            from risks r
            join projects p on p.key = r.project_key
            where r.status not in ('已关闭', '已解决')
            """
        ).fetchone()
        project_rows = connection.execute("select * from projects").fetchall()
        project_health_scores = [
            calculate_project_health_from_db(connection, row_to_dict(row))["health"]
            for row in project_rows
        ]
    payload = row_to_dict(project_row)
    task_payload = row_to_dict(task_row)
    risk_payload = row_to_dict(risk_row)
    risk_count = risk_payload["risk_count"] or 0
    avg_progress = task_payload["avg_task_progress"] or payload["avg_progress"] or 0
    return {
        "total": payload["total"] or 0,
        "dashboard_count": payload["dashboard_count"] or 0,
        "avg_progress": round(avg_progress),
        "task_count": task_payload["task_count"] or 0,
        "risk_count": risk_count,
        "avg_health": round(sum(project_health_scores) / len(project_health_scores)) if project_health_scores else 0,
    }


@router.post("")
def create_project(project: ProjectCreate) -> dict:
    init_db()
    payload = apply_budget_usage(project.model_dump())
    base_key = payload["key"] or make_project_key(payload["name"])
    key = base_key
    with get_connection() as connection:
        suffix = 1
        while connection.execute("select 1 from projects where key = ?", [key]).fetchone():
            suffix += 1
            key = f"{base_key}-{suffix}"
        payload["key"] = key
        payload["dashboard"] = 1 if payload["dashboard"] else 0
        columns = [column for column in PROJECT_COLUMNS if column in payload]
        placeholders = ", ".join(["?"] * len(columns))
        connection.execute(
            f"insert into projects ({', '.join(columns)}) values ({placeholders})",
            [payload[column] for column in columns],
        )
        connection.commit()
        row = connection.execute("select * from projects where key = ?", [key]).fetchone()
        return normalize_project(apply_project_metrics(row_to_dict(row), connection))


@router.put("/{project_key}")
def update_project(project_key: str, project: ProjectUpdate) -> dict:
    init_db()
    payload = apply_budget_usage(project.model_dump())
    payload["dashboard"] = 1 if payload["dashboard"] else 0
    columns = [column for column in PROJECT_COLUMNS if column != "key" and column in payload]
    assignments = ", ".join([f"{column} = ?" for column in columns])
    with get_connection() as connection:
        result = connection.execute(
            f"update projects set {assignments} where key = ?",
            [payload[column] for column in columns] + [project_key],
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Project not found")
        connection.commit()
        row = connection.execute("select * from projects where key = ?", [project_key]).fetchone()
        return normalize_project(apply_project_metrics(row_to_dict(row), connection))


@router.get("/{project_key}/gantt")
def get_project_gantt(project_key: str) -> dict:
    init_db()
    with get_connection() as connection:
        project = connection.execute("select 1 from projects where key = ?", [project_key]).fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        row = connection.execute("select rows_json from project_gantt where project_key = ?", [project_key]).fetchone()
        if not row:
            return {"project_key": project_key, "rows": []}
        try:
            rows = json.loads(row["rows_json"])
        except json.JSONDecodeError:
            rows = []
        return {"project_key": project_key, "rows": rows if isinstance(rows, list) else []}


@router.put("/{project_key}/gantt")
def save_project_gantt(project_key: str, payload: GanttRowsPayload) -> dict:
    init_db()
    rows_json = json.dumps(payload.rows, ensure_ascii=False)
    with get_connection() as connection:
        project = connection.execute("select 1 from projects where key = ?", [project_key]).fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        connection.execute(
            """
            insert into project_gantt (project_key, rows_json, updated_at)
            values (?, ?, current_timestamp)
            on conflict(project_key) do update set
              rows_json = excluded.rows_json,
              updated_at = current_timestamp
            """,
            [project_key, rows_json],
        )
        connection.commit()
    return {"project_key": project_key, "rows": payload.rows}


@router.patch("/{project_key}/dashboard")
def update_dashboard_flag(project_key: str, payload: dict[str, bool]) -> dict:
    init_db()
    dashboard = bool(payload.get("dashboard", True))
    with get_connection() as connection:
        result = connection.execute(
            "update projects set dashboard = ? where key = ?",
            [1 if dashboard else 0, project_key],
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Project not found")
        connection.commit()
        row = connection.execute("select * from projects where key = ?", [project_key]).fetchone()
        return normalize_project(apply_project_metrics(row_to_dict(row), connection))


@router.delete("/{project_key}")
def delete_project(project_key: str) -> dict[str, str]:
    init_db()
    with get_connection() as connection:
        result = connection.execute("delete from projects where key = ?", [project_key])
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Project not found")
        connection.commit()
    return {"status": "deleted", "key": project_key}
