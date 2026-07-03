from pathlib import Path
import shutil

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.db import EXPORTS_DIR, TEMPLATES_DIR, get_connection, init_db, row_to_dict
from app.schemas import DocumentGenerateRequest
from app.services.document_service import (
    export_markdown_to_docx,
    extract_docx_text,
    generate_markdown,
    get_project_context,
    markdown_to_html,
    safe_filename,
)


router = APIRouter(tags=["documents"])


def normalize_template(row: dict) -> dict:
    return row


def normalize_version(row: dict) -> dict:
    row["export_url"] = f"/api/document-exports/{Path(row['export_path']).name}" if row.get("export_path") else ""
    return row


def unlink_managed_file(file_path: str) -> bool:
    if not file_path:
        return False
    path = Path(file_path)
    managed_dirs = {TEMPLATES_DIR.resolve(), EXPORTS_DIR.resolve()}
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if resolved.parent not in managed_dirs or not resolved.exists() or not resolved.is_file():
        return False
    resolved.unlink()
    return True


@router.get("/document-templates")
def list_document_templates() -> list[dict]:
    init_db()
    with get_connection() as connection:
        rows = connection.execute("select * from document_templates order by id desc").fetchall()
    return [normalize_template(row_to_dict(row)) for row in rows]


@router.post("/document-templates/upload")
def upload_document_template(
    name: str = Form(...),
    template_type: str = Form("srs"),
    file: UploadFile = File(...),
) -> dict:
    init_db()
    if not name.strip():
        raise HTTPException(status_code=400, detail="Template name is required")
    suffix = Path(file.filename or "template").suffix
    with get_connection() as connection:
        cursor = connection.execute(
            """
            insert into document_templates
              (name, template_type, original_filename, file_path, status, variables)
            values (?, ?, ?, '', 'enabled', ?)
            """,
            [
                name.strip(),
                template_type,
                file.filename or "",
                "项目、任务、风险、需求、里程碑",
            ],
        )
        template_id = cursor.lastrowid
        target_path = TEMPLATES_DIR / f"template-{template_id}{suffix}"
        with target_path.open("wb") as output:
            shutil.copyfileobj(file.file, output)
        connection.execute(
            "update document_templates set file_path = ?, updated_at = current_timestamp where id = ?",
            [str(target_path), template_id],
        )
        connection.commit()
        row = connection.execute("select * from document_templates where id = ?", [template_id]).fetchone()
    return normalize_template(row_to_dict(row))


@router.delete("/document-templates/{template_id}")
def delete_document_template(template_id: int) -> dict:
    init_db()
    with get_connection() as connection:
        row = connection.execute("select * from document_templates where id = ?", [template_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Template not found")
        template = row_to_dict(row)
        version_rows = connection.execute(
            "select export_path from document_versions where template_id = ? and export_path != ''",
            [template_id],
        ).fetchall()
        connection.execute("delete from document_templates where id = ?", [template_id])
        connection.commit()
    removed_files = 0
    for file_path in [template.get("file_path", ""), *(row["export_path"] for row in version_rows)]:
        if unlink_managed_file(file_path):
            removed_files += 1
    return {"deleted": True, "template_id": template_id, "removed_files": removed_files}


@router.post("/document-content/extract")
async def extract_document_content(file: UploadFile = File(...)) -> dict[str, str]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".docx":
        raise HTTPException(status_code=400, detail="Only .docx content files are supported")
    try:
        file.file.seek(0)
        content = extract_docx_text(file.file)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Failed to read .docx content") from exc
    if not content:
        raise HTTPException(status_code=400, detail="No readable text found in .docx")
    return {"filename": file.filename or "", "content": content}


@router.get("/document-versions")
def list_document_versions(project_key: str = "", template_id: int | None = None) -> list[dict]:
    init_db()
    where: list[str] = []
    params: list[str | int] = []
    if project_key:
        where.append("project_key = ?")
        params.append(project_key)
    if template_id:
        where.append("template_id = ?")
        params.append(template_id)
    sql = "select * from document_versions"
    if where:
        sql += " where " + " and ".join(where)
    sql += " order by id desc"
    with get_connection() as connection:
        rows = connection.execute(sql, params).fetchall()
    return [normalize_version(row_to_dict(row)) for row in rows]


@router.post("/document-versions/generate")
def generate_document_version(request: DocumentGenerateRequest) -> dict:
    init_db()
    with get_connection() as connection:
        template_row = connection.execute(
            "select * from document_templates where id = ?",
            [request.template_id],
        ).fetchone()
        if not template_row:
            raise HTTPException(status_code=404, detail="Template not found")
        template = row_to_dict(template_row)
        try:
            context = get_project_context(connection, request.project_key)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        markdown = generate_markdown(context, template, request.title, request.input_content)
        html = markdown_to_html(markdown)
        version_row = connection.execute(
            """
            select coalesce(max(version), 0) + 1 as next_version
            from document_versions
            where project_key = ? and template_id = ?
            """,
            [request.project_key, request.template_id],
        ).fetchone()
        version = version_row["next_version"] or 1
        title = request.title or markdown.splitlines()[0].replace("# ", "")
        cursor = connection.execute(
            """
            insert into document_versions
              (project_key, template_id, title, content_markdown, content_html, version)
            values (?, ?, ?, ?, ?, ?)
            """,
            [request.project_key, request.template_id, title, markdown, html, version],
        )
        connection.commit()
        row = connection.execute("select * from document_versions where id = ?", [cursor.lastrowid]).fetchone()
    return normalize_version(row_to_dict(row))


@router.post("/document-versions/{version_id}/export-word")
def export_document_word(version_id: int) -> dict:
    init_db()
    with get_connection() as connection:
        row = connection.execute("select * from document_versions where id = ?", [version_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document version not found")
        version = row_to_dict(row)
        template_row = connection.execute("select * from document_templates where id = ?", [version["template_id"]]).fetchone()
        template = row_to_dict(template_row) if template_row else {}
        try:
            context = get_project_context(connection, version["project_key"])
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        filename = f"version-{version_id}-{safe_filename(version['title'])}.docx"
        output_path = EXPORTS_DIR / filename
        export_markdown_to_docx(
            version["content_markdown"],
            output_path,
            template.get("file_path", ""),
            context=context,
            template=template,
        )
        connection.execute(
            """
            update document_versions
            set word_status = 'exported', export_path = ?
            where id = ?
            """,
            [str(output_path), version_id],
        )
        connection.commit()
        updated = connection.execute("select * from document_versions where id = ?", [version_id]).fetchone()
    return normalize_version(row_to_dict(updated))


@router.get("/document-exports/{filename}")
def download_document_export(filename: str) -> FileResponse:
    path = EXPORTS_DIR / filename
    if not path.exists() or path.parent != EXPORTS_DIR:
        raise HTTPException(status_code=404, detail="Export not found")
    return FileResponse(path, filename=filename)
