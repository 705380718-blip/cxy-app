from fastapi import APIRouter, HTTPException

from app.db import get_connection, init_db, row_to_dict
from app.schemas import DemandBase, DemandUpdate, MilestoneBase, MilestoneUpdate, RiskBase, RiskUpdate, TaskBase, TaskUpdate
from app.services.health_score_service import CLOSED_STATUSES, calculate_project_health_from_db


router = APIRouter(tags=["project-assets"])


ASSESSMENT_DONE_DEMAND_STATUS = "已完成"


def list_rows(table: str, project_key: str = "", status: str = "") -> list[dict]:
    init_db()
    sql = f"select * from {table}"
    params: list[str] = []
    if project_key:
        sql += " where project_key = ?"
        params.append(project_key)
    if status:
        sql += " and status = ?" if project_key else " where status = ?"
        params.append(status)
    order_by = "due_date asc, id desc" if table == "tasks" else "id desc"
    sql += f" order by {order_by}"
    with get_connection() as connection:
        return [row_to_dict(row) for row in connection.execute(sql, params).fetchall()]


def insert_row(table: str, payload: dict) -> dict:
    init_db()
    columns = list(payload.keys())
    placeholders = ", ".join(["?"] * len(columns))
    with get_connection() as connection:
        cursor = connection.execute(
            f"insert into {table} ({', '.join(columns)}) values ({placeholders})",
            [payload[column] for column in columns],
        )
        connection.commit()
        row = connection.execute(f"select * from {table} where id = ?", [cursor.lastrowid]).fetchone()
    return row_to_dict(row)


@router.get("/tasks")
def list_tasks(project_key: str = "", status: str = "") -> list[dict]:
    return list_rows("tasks", project_key, status)


@router.get("/tasks/calendar")
def task_calendar(project_key: str = "", month: str = "") -> dict[str, list[dict]]:
    init_db()
    task_sql = "select * from tasks"
    milestone_sql = "select * from milestones"
    params: list[str] = []
    milestone_params: list[str] = []
    where: list[str] = []
    milestone_where: list[str] = []
    if project_key:
        where.append("project_key = ?")
        milestone_where.append("project_key = ?")
        params.append(project_key)
        milestone_params.append(project_key)
    if month:
        where.append("due_date like ?")
        milestone_where.append("date like ?")
        params.append(f"{month}%")
        milestone_params.append(f"{month}%")
    if where:
        task_sql += " where " + " and ".join(where)
    if milestone_where:
        milestone_sql += " where " + " and ".join(milestone_where)
    task_sql += " order by due_date asc, id desc"
    milestone_sql += " order by date asc, id desc"
    with get_connection() as connection:
        tasks = [row_to_dict(row) for row in connection.execute(task_sql, params).fetchall()]
        milestones = [
            row_to_dict(row) for row in connection.execute(milestone_sql, milestone_params).fetchall()
        ]
    return {"tasks": tasks, "milestones": milestones}


@router.post("/tasks")
def create_task(task: TaskBase) -> dict:
    return insert_row("tasks", task.model_dump())


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, task: TaskUpdate) -> dict:
    init_db()
    payload = task.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No task fields to update")
    columns = list(payload.keys())
    assignments = ", ".join([f"{column} = ?" for column in columns])
    with get_connection() as connection:
        result = connection.execute(
            f"update tasks set {assignments} where id = ?",
            [payload[column] for column in columns] + [task_id],
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")
        row = connection.execute("select * from tasks where id = ?", [task_id]).fetchone()
        task_row = row_to_dict(row)
        if task_row.get("status") == "done" and task_row.get("demand_id"):
            connection.execute(
                f"""
                update demands
                set status = ?
                where id = ?
                  and project_key = ?
                  and status not in ({", ".join(["?"] * len(CLOSED_STATUSES))})
                """,
                [ASSESSMENT_DONE_DEMAND_STATUS, task_row["demand_id"], task_row["project_key"], *CLOSED_STATUSES],
            )
        connection.commit()
    return task_row


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int) -> dict[str, int | str]:
    init_db()
    with get_connection() as connection:
        result = connection.execute("delete from tasks where id = ?", [task_id])
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Task not found")
        connection.commit()
    return {"status": "deleted", "id": task_id}


@router.get("/risks")
def list_risks(project_key: str = "") -> list[dict]:
    return list_rows("risks", project_key)


@router.post("/risks")
def create_risk(risk: RiskBase) -> dict:
    return insert_row("risks", risk.model_dump())


@router.get("/risks/summary")
def risk_summary(project_key: str = "") -> dict:
    init_db()
    where = " where project_key = ?" if project_key else ""
    params = [project_key] if project_key else []
    health_payload = {"health": 0, "signals": {}}
    with get_connection() as connection:
        row = connection.execute(
            f"""
            select
              count(*) as total,
              sum(case when impact = '高' then 1 else 0 end) as high_count,
              sum(case when status not in ('已关闭', '已解决') then 1 else 0 end) as open_count
            from risks
            {where}
            """,
            params,
        ).fetchone()
        demand_row = connection.execute(
            f"select count(*) as total from demands{where}",
            params,
        ).fetchone()
        progress_row = connection.execute(
            f"select avg(progress) as avg_progress from tasks{where}",
            params,
        ).fetchone()
        if project_key:
            project_row = connection.execute("select * from projects where key = ?", [project_key]).fetchone()
            if project_row:
                health_payload = calculate_project_health_from_db(connection, row_to_dict(project_row))
    risk_payload = row_to_dict(row)
    signals = health_payload.get("signals", {})
    return {
        "total": risk_payload["total"] or 0,
        "high_count": risk_payload["high_count"] or 0,
        "open_count": risk_payload["open_count"] or 0,
        "demand_count": row_to_dict(demand_row)["total"] or 0,
        "avg_task_progress": round(row_to_dict(progress_row)["avg_progress"] or 0),
        "health": health_payload["health"],
        "overdue_tasks": signals.get("overdue_tasks", 0),
        "due_soon_tasks": signals.get("due_soon_tasks", 0),
        "overdue_milestones": signals.get("overdue_milestones", 0),
        "due_soon_milestones": signals.get("due_soon_milestones", 0),
    }


@router.patch("/risks/{risk_id}")
def update_risk(risk_id: int, risk: RiskUpdate) -> dict:
    init_db()
    payload = risk.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No risk fields to update")
    columns = list(payload.keys())
    assignments = ", ".join([f"{column} = ?" for column in columns])
    with get_connection() as connection:
        result = connection.execute(
            f"update risks set {assignments} where id = ?",
            [payload[column] for column in columns] + [risk_id],
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Risk not found")
        connection.commit()
        row = connection.execute("select * from risks where id = ?", [risk_id]).fetchone()
    return row_to_dict(row)


@router.get("/demands")
def list_demands(project_key: str = "") -> list[dict]:
    init_db()
    params: list[str] = []
    where = ""
    if project_key:
        where = "where d.project_key = ?"
        params.append(project_key)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            select
              d.*,
              e.item_type as source_item_type,
              e.title as source_title,
              s.source_type as source_type,
              s.raw_text as source_text,
              s.created_at as source_created_at
            from demands d
            left join extractions e on e.id = d.source_extraction_id
            left join snippets s on s.id = e.snippet_id
            {where}
            order by d.id desc
            """,
            params,
        ).fetchall()
    return [row_to_dict(row) for row in rows]


@router.post("/demands")
def create_demand(demand: DemandBase) -> dict:
    return insert_row("demands", demand.model_dump())


@router.patch("/demands/{demand_id}")
def update_demand(demand_id: int, demand: DemandUpdate) -> dict:
    init_db()
    payload = demand.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No demand fields to update")
    columns = list(payload.keys())
    assignments = ", ".join([f"{column} = ?" for column in columns])
    with get_connection() as connection:
        result = connection.execute(
            f"update demands set {assignments} where id = ?",
            [payload[column] for column in columns] + [demand_id],
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Demand not found")
        connection.commit()
        row = connection.execute("select * from demands where id = ?", [demand_id]).fetchone()
    return row_to_dict(row)


@router.delete("/demands/{demand_id}")
def delete_demand(demand_id: int) -> dict[str, int | str]:
    init_db()
    with get_connection() as connection:
        result = connection.execute("delete from demands where id = ?", [demand_id])
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Demand not found")
        connection.commit()
    return {"status": "deleted", "id": demand_id}


@router.get("/milestones")
def list_milestones(project_key: str = "") -> list[dict]:
    return list_rows("milestones", project_key)


@router.post("/milestones")
def create_milestone(milestone: MilestoneBase) -> dict:
    return insert_row("milestones", milestone.model_dump())


@router.patch("/milestones/{milestone_id}")
def update_milestone(milestone_id: int, milestone: MilestoneUpdate) -> dict:
    init_db()
    payload = milestone.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No milestone fields to update")
    columns = list(payload.keys())
    assignments = ", ".join([f"{column} = ?" for column in columns])
    with get_connection() as connection:
        result = connection.execute(
            f"update milestones set {assignments} where id = ?",
            [payload[column] for column in columns] + [milestone_id],
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Milestone not found")
        connection.commit()
        row = connection.execute("select * from milestones where id = ?", [milestone_id]).fetchone()
    return row_to_dict(row)


@router.delete("/milestones/{milestone_id}")
def delete_milestone(milestone_id: int) -> dict[str, int | str]:
    init_db()
    with get_connection() as connection:
        result = connection.execute("delete from milestones where id = ?", [milestone_id])
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Milestone not found")
        connection.commit()
    return {"status": "deleted", "id": milestone_id}
