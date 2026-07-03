from fastapi import APIRouter, HTTPException

from app.db import get_connection, init_db, row_to_dict
from app.schemas import ExtractionUpdate, SnippetCreate
from app.services.extraction_service import extract_structured_items
from app.services.settings_service import get_model_config


router = APIRouter(tags=["inbox"])


EXTRACTION_COLUMNS = [
    "item_type",
    "title",
    "description",
    "owner",
    "due_date",
    "probability",
    "impact",
    "response",
    "status",
]


def get_extraction(connection, extraction_id: int) -> dict:
    row = connection.execute("select * from extractions where id = ?", [extraction_id]).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Extraction not found")
    return row_to_dict(row)


def insert_target_record(connection, extraction: dict) -> tuple[str, int]:
    item_type = extraction["item_type"]
    if item_type == "task":
        cursor = connection.execute(
            """
            insert into tasks
              (project_key, status, title, description, owner, due_date, progress, source_extraction_id)
            values (?, 'todo', ?, ?, ?, ?, 0, ?)
            """,
            [
                extraction["project_key"],
                extraction["title"],
                extraction["description"],
                extraction["owner"],
                extraction["due_date"],
                extraction["id"],
            ],
        )
        return "tasks", cursor.lastrowid
    if item_type == "risk":
        cursor = connection.execute(
            """
            insert into risks
              (project_key, title, description, probability, impact, status, response, source_extraction_id)
            values (?, ?, ?, ?, ?, '跟进中', ?, ?)
            """,
            [
                extraction["project_key"],
                extraction["title"],
                extraction["description"],
                extraction["probability"],
                extraction["impact"] or "中",
                extraction["response"],
                extraction["id"],
            ],
        )
        return "risks", cursor.lastrowid
    if item_type == "demand":
        cursor = connection.execute(
            """
            insert into demands
              (project_key, title, description, status, scope_impact, source_extraction_id)
            values (?, ?, ?, '待评估', ?, ?)
            """,
            [
                extraction["project_key"],
                extraction["title"],
                extraction["description"],
                extraction["response"] or "待评估范围",
                extraction["id"],
            ],
        )
        return "demands", cursor.lastrowid
    if item_type == "milestone":
        cursor = connection.execute(
            """
            insert into milestones
              (project_key, title, date, status, source_extraction_id)
            values (?, ?, ?, '待开始', ?)
            """,
            [
                extraction["project_key"],
                extraction["title"],
                extraction["due_date"],
                extraction["id"],
            ],
        )
        return "milestones", cursor.lastrowid
    raise HTTPException(status_code=400, detail="Unsupported extraction type")


@router.get("/snippets")
def list_snippets(project_key: str = "") -> list[dict]:
    init_db()
    sql = "select * from snippets"
    params: list[str] = []
    if project_key:
        sql += " where project_key = ?"
        params.append(project_key)
    sql += " order by id desc"
    with get_connection() as connection:
        return [row_to_dict(row) for row in connection.execute(sql, params).fetchall()]


@router.post("/snippets")
def create_snippet(snippet: SnippetCreate) -> dict:
    init_db()
    with get_connection() as connection:
        project = connection.execute("select 1 from projects where key = ?", [snippet.project_key]).fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        cursor = connection.execute(
            """
            insert into snippets (project_key, source_type, raw_text, extract_status)
            values (?, ?, ?, 'pending')
            """,
            [snippet.project_key, snippet.source_type, snippet.raw_text],
        )
        connection.commit()
        row = connection.execute("select * from snippets where id = ?", [cursor.lastrowid]).fetchone()
    return row_to_dict(row)


@router.post("/snippets/{snippet_id}/extract")
def extract_snippet(snippet_id: int) -> dict:
    init_db()
    with get_connection() as connection:
        snippet_row = connection.execute("select * from snippets where id = ?", [snippet_id]).fetchone()
        if not snippet_row:
            raise HTTPException(status_code=404, detail="Snippet not found")
        snippet = row_to_dict(snippet_row)

    model_config = get_model_config()
    drafts = extract_structured_items(snippet["raw_text"], model_config)

    with get_connection() as connection:
        connection.execute("delete from extractions where snippet_id = ? and status = 'pending'", [snippet_id])
        for draft in drafts:
            connection.execute(
                """
                insert into extractions
                  (snippet_id, project_key, item_type, title, description, owner, due_date,
                   probability, impact, response, status)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                [
                    snippet_id,
                    snippet["project_key"],
                    draft["item_type"],
                    draft["title"],
                    draft["description"],
                    draft["owner"],
                    draft["due_date"],
                    draft["probability"],
                    draft["impact"],
                    draft["response"],
                ],
            )
        connection.execute(
            "update snippets set extract_status = ? where id = ?",
            ["extracted" if drafts else "empty", snippet_id],
        )
        connection.commit()
        rows = connection.execute(
            "select * from extractions where snippet_id = ? order by id asc",
            [snippet_id],
        ).fetchall()
    return {"snippet_id": snippet_id, "items": [row_to_dict(row) for row in rows]}


@router.get("/extractions")
def list_extractions(project_key: str = "", status: str = "pending") -> list[dict]:
    init_db()
    where: list[str] = []
    params: list[str] = []
    if project_key:
        where.append("project_key = ?")
        params.append(project_key)
    if status:
        where.append("status = ?")
        params.append(status)
    sql = "select * from extractions"
    if where:
        sql += " where " + " and ".join(where)
    sql += " order by id desc"
    with get_connection() as connection:
        return [row_to_dict(row) for row in connection.execute(sql, params).fetchall()]


@router.patch("/extractions/{extraction_id}")
def update_extraction(extraction_id: int, extraction: ExtractionUpdate) -> dict:
    init_db()
    payload = extraction.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No extraction fields to update")
    columns = [column for column in EXTRACTION_COLUMNS if column in payload]
    assignments = ", ".join([f"{column} = ?" for column in columns])
    with get_connection() as connection:
        result = connection.execute(
            f"update extractions set {assignments} where id = ?",
            [payload[column] for column in columns] + [extraction_id],
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Extraction not found")
        connection.commit()
        return get_extraction(connection, extraction_id)


@router.post("/extractions/{extraction_id}/confirm")
def confirm_extraction(extraction_id: int) -> dict:
    init_db()
    with get_connection() as connection:
        extraction = get_extraction(connection, extraction_id)
        if extraction["status"] == "confirmed":
            return extraction
        target_table, target_record_id = insert_target_record(connection, extraction)
        connection.execute(
            """
            update extractions
            set status = 'confirmed', target_table = ?, target_record_id = ?
            where id = ?
            """,
            [target_table, target_record_id, extraction_id],
        )
        connection.commit()
        return get_extraction(connection, extraction_id)
