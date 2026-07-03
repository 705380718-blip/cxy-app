from pathlib import Path
import json
import os
import sqlite3
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.environ.get("AI_PM_DB_PATH", DATA_DIR / "app.db"))
STORAGE_DIR = Path(os.environ.get("AI_PM_STORAGE_DIR", PROJECT_DIR / "storage"))
TEMPLATES_DIR = STORAGE_DIR / "templates"
EXPORTS_DIR = STORAGE_DIR / "exports"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma foreign_keys = on")
    return connection


PROJECT_SEED: list[dict[str, Any]] = [
    {
        "key": "gov",
        "name": "智慧政务平台建设项目",
        "customer": "某市大数据管理局",
        "phase": "实施中",
        "status": "配合销售、售前推进",
        "contract_status": "已签合同",
        "region": "江苏南京",
        "area": "江苏区",
        "project_type": "政务大数据",
        "progress": 68,
        "days": "23",
        "tasks": 12,
        "risks": 3,
        "budget_usage": 45,
        "new_demands": 3,
        "health": 82,
        "budget": "300万",
        "incurred_cost": "135万",
        "payment_2025": "120万",
        "manager": "陈晓勇",
        "delivery": "李工、王工",
        "sales": "袁伟",
        "start_date": "2026-03-01",
        "pre_start_date": "2026-02-18",
        "acceptance": "2026Q3",
        "end_date": "2026-10-31",
        "spm": "S260001",
        "contract_no": "XYSZ26001",
        "background": "政务服务平台升级与数据治理配套建设。",
        "plan": "需求评审、环境部署、联调验收、运维支持。",
        "remark": "重点关注 5/28 需求评审。",
        "dashboard": 1,
        "milestone_date": "5/28",
        "milestone_label": "下一里程碑 · 需求评审",
    },
    {
        "key": "data",
        "name": "企业数据中台建设",
        "customer": "市属国企集团",
        "phase": "实施中",
        "status": "正常实施",
        "contract_status": "已签合同",
        "region": "湖北武汉",
        "area": "华中区",
        "project_type": "企业项目",
        "progress": 42,
        "days": "45",
        "tasks": 8,
        "risks": 1,
        "budget_usage": 38,
        "new_demands": 1,
        "health": 86,
        "budget": "240万",
        "incurred_cost": "91.2万",
        "payment_2025": "80万",
        "manager": "陈晓勇",
        "delivery": "周工",
        "sales": "王博",
        "start_date": "2026-04-01",
        "pre_start_date": "2026-03-15",
        "acceptance": "2026Q4",
        "end_date": "2026-11-30",
        "spm": "S260002",
        "contract_no": "XYSF26002",
        "background": "集团统一数据中台与指标体系建设。",
        "plan": "数据源接入、指标模型、权限方案、试运行验收。",
        "remark": "接口文档口径需补齐。",
        "dashboard": 1,
        "milestone_date": "6/12",
        "milestone_label": "下一里程碑 · 数据源联调",
    },
    {
        "key": "parking",
        "name": "园区智慧停车方案",
        "customer": "某产业园管委会",
        "phase": "预投入",
        "status": "配合销售、售前推进",
        "contract_status": "未签合同",
        "region": "四川成都",
        "area": "西南区",
        "project_type": "政务大数据",
        "progress": 35,
        "days": "-",
        "tasks": 3,
        "risks": 0,
        "budget_usage": 22,
        "new_demands": 2,
        "health": 90,
        "budget": "待定",
        "incurred_cost": "",
        "payment_2025": "-",
        "manager": "陈晓勇",
        "delivery": "售前支持组",
        "sales": "左琦",
        "start_date": "待定",
        "pre_start_date": "2026-05-20",
        "acceptance": "待定",
        "end_date": "待定",
        "spm": "S260003",
        "contract_no": "-",
        "background": "园区停车资源整合与智慧管理方案。",
        "plan": "需求澄清、现场踏勘、方案初稿、报价测算。",
        "remark": "预算口径待确认。",
        "dashboard": 1,
        "milestone_date": "本周五",
        "milestone_label": "下一节点 · 方案提交",
    },
    {
        "key": "ops",
        "name": "人力资源管理系统运维",
        "customer": "某人社局",
        "phase": "运维",
        "status": "移交本地",
        "contract_status": "已签合同",
        "region": "天津",
        "area": "华北区",
        "project_type": "云交付",
        "progress": 100,
        "days": "-",
        "tasks": 1,
        "risks": 0,
        "budget_usage": 71,
        "new_demands": 0,
        "health": 94,
        "budget": "60万/年",
        "incurred_cost": "42.6万",
        "payment_2025": "60万",
        "manager": "陈晓勇",
        "delivery": "运维组",
        "sales": "张永满",
        "start_date": "2025-04-01",
        "pre_start_date": "",
        "acceptance": "2025Q4",
        "end_date": "2027-03-31",
        "spm": "S250004",
        "contract_no": "XYSZ25004",
        "background": "人社局存量系统年度运维服务。",
        "plan": "问题响应、月度巡检、备份检查、年度服务报告。",
        "remark": "不默认展示到驾驶舱。",
        "dashboard": 0,
        "milestone_date": "月底",
        "milestone_label": "下一节点 · 月度巡检",
    },
]


TASK_SEED = [
    ("gov", "confirm", "补齐短信验证码异常场景", "来源：飞书群聊 · 建议责任人：李工", "李工", "2026-05-24", 0),
    ("gov", "todo", "完成需求规格说明书 V1.0", "评审前必须完成", "张三", "2026-05-26", 0),
    ("gov", "doing", "需求分析", "完成度 60% · 影响 5/28 评审", "张三", "2026-05-28", 60),
    ("gov", "done", "项目启动会", "会议纪要已归档", "陈晓勇", "2026-05-20", 100),
    ("data", "todo", "补齐数据源接入清单", "覆盖财务、人事、项目三类系统", "周工", "2026-05-30", 0),
    ("parking", "doing", "现场踏勘问题清单", "已完成 40%", "项目组", "2026-05-24", 40),
]


RISK_SEED = [
    ("gov", "天气 API 文档未到位", "可能影响联调排期", "60%", "中", "跟进中", "联系供应商升级 SLA"),
    ("gov", "需求评审临近", "关键任务完成度不足", "70%", "高", "跟进中", "确认剩余需求清单"),
    ("data", "财务系统接口口径不完整", "可能影响数据源接入", "45%", "中", "观察中", "补齐字段说明"),
]


DEMAND_SEED = [
    ("gov", "首页增加办件进度提醒", "客户新增诉求，需要评估范围", "待评估", "可能影响 5/28 评审"),
    ("parking", "停车泊位地图联动", "园区希望增加地图交互", "待评估", "影响报价测算"),
]


MILESTONE_SEED = [
    ("gov", "需求评审会", "2026-05-28", "待开始"),
    ("data", "数据源联调", "2026-06-12", "待开始"),
    ("parking", "方案提交", "2026-05-29", "待开始"),
]


DEFAULT_MODEL_CONFIG: dict[str, Any] = {
    "provider": "mock",
    "provider_label": "离线内置模型",
    "model": "local-project-assistant",
    "base_url": "",
    "api_key": "",
    "verify_ssl": True,
    "temperature": 0.1,
    "status": "untested",
    "status_message": "尚未测试连接。",
    "last_tested_at": "",
    "overrides": [
        {
            "capability": "extract",
            "label": "信息提取",
            "mode": "inherit",
            "provider": "",
            "model": "",
            "base_url": "",
        },
        {
            "capability": "documents",
            "label": "文档生成",
            "mode": "inherit",
            "provider": "",
            "model": "",
            "base_url": "",
        },
        {
            "capability": "risk",
            "label": "风险分析",
            "mode": "inherit",
            "provider": "",
            "model": "",
            "base_url": "",
        },
        {
            "capability": "assistant",
            "label": "AI 助手",
            "mode": "inherit",
            "provider": "",
            "model": "",
            "base_url": "",
        },
    ],
}


DEFAULT_AGENT_PROFILE: dict[str, Any] = {
    "name": "小智",
    "role": "辅助项目经理完成项目管理，减轻重复工作量，辅助决策，主动提示风险",
    "tone": "理性，沉稳",
    "responsibilities": [
        "项目进度跟进",
        "及时提醒项目风险、进度等问题",
        "辅助文档生成，减轻项目经理的文档工作",
    ],
    "forbidden": [
        "篡改项目信息",
        "将项目信息和人物信息发布到互联网",
        "透露 API Key 或其他敏感配置",
    ],
    "default_output_format": "飞书可展示的 Markdown 格式",
    "long_term_preferences": [
        "提醒和顾问型",
        "优先基于当前项目数据和历史对话回答",
        "缺少数据时明确指出缺口并给出补充建议",
    ],
    "proactive_reminders": [
        "项目风险",
        "每日待办",
        "任务进度逾期",
    ],
    "memory_policy": "智能体画像、项目历史对话和项目数据保存在本地 SQLite 中，与底层模型配置分离；切换模型不改变智能体身份与记忆。",
}


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def seed_defaults(connection: sqlite3.Connection) -> None:
    project_count = connection.execute("select count(*) from projects").fetchone()[0]
    if project_count:
        connection.execute(
            """
            insert into app_meta (key, value)
            values ('defaults_seeded', 'true')
            on conflict(key) do update set value = excluded.value
            """
        )
        return

    seeded_row = connection.execute(
        "select value from app_meta where key = 'defaults_seeded'",
    ).fetchone()
    if seeded_row:
        return

    project_columns = list(PROJECT_SEED[0].keys())
    placeholders = ", ".join(["?"] * len(project_columns))
    connection.executemany(
        f"insert into projects ({', '.join(project_columns)}) values ({placeholders})",
        [[project[column] for column in project_columns] for project in PROJECT_SEED],
    )
    connection.executemany(
        """
        insert into tasks (project_key, status, title, description, owner, due_date, progress)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        TASK_SEED,
    )
    connection.executemany(
        """
        insert into risks (project_key, title, description, probability, impact, status, response)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        RISK_SEED,
    )
    connection.executemany(
        """
        insert into demands (project_key, title, description, status, scope_impact)
        values (?, ?, ?, ?, ?)
        """,
        DEMAND_SEED,
    )
    connection.executemany(
        """
        insert into milestones (project_key, title, date, status)
        values (?, ?, ?, ?)
        """,
        MILESTONE_SEED,
    )
    connection.execute(
        """
        insert into app_meta (key, value)
        values ('defaults_seeded', 'true')
        on conflict(key) do update set value = excluded.value
        """
    )


def ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing_columns = {
        row["name"]
        for row in connection.execute(f"pragma table_info({table})").fetchall()
    }
    if column not in existing_columns:
        connection.execute(f"alter table {table} add column {column} {definition}")


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            create table if not exists app_meta (
              key text primary key,
              value text not null
            )
            """
        )
        connection.execute(
            """
            insert into app_meta (key, value)
            values ('schema_version', 'p6')
            on conflict(key) do update set value = excluded.value
            """
        )
        connection.execute(
            """
            insert into app_meta (key, value)
            values ('ai_model_config', ?)
            on conflict(key) do nothing
            """,
            [json.dumps(DEFAULT_MODEL_CONFIG, ensure_ascii=False)],
        )
        connection.execute(
            """
            insert into app_meta (key, value)
            values ('agent_profile', ?)
            on conflict(key) do nothing
            """,
            [json.dumps(DEFAULT_AGENT_PROFILE, ensure_ascii=False)],
        )
        connection.execute(
            """
            create table if not exists projects (
              key text primary key,
              name text not null,
              customer text not null default '',
              phase text not null default '',
              status text not null default '',
              contract_status text not null default '',
              region text not null default '',
              area text not null default '',
              project_type text not null default '',
              progress integer not null default 0,
              days text not null default '',
              tasks integer not null default 0,
              risks integer not null default 0,
              budget_usage integer not null default 0,
              new_demands integer not null default 0,
              health integer not null default 0,
              budget text not null default '',
              incurred_cost text not null default '',
              payment_2025 text not null default '',
              manager text not null default '',
              delivery text not null default '',
              sales text not null default '',
              start_date text not null default '',
              pre_start_date text not null default '',
              acceptance text not null default '',
              end_date text not null default '',
              spm text not null default '',
              contract_no text not null default '',
              background text not null default '',
              plan text not null default '',
              remark text not null default '',
              dashboard integer not null default 1,
              milestone_date text not null default '',
              milestone_label text not null default ''
            )
            """
        )
        ensure_column(connection, "projects", "incurred_cost", "text not null default ''")
        connection.execute(
            """
            create table if not exists tasks (
              id integer primary key autoincrement,
              project_key text not null,
              status text not null default 'todo',
              title text not null,
              description text not null default '',
              owner text not null default '',
              start_date text not null default '',
              due_date text not null default '',
              progress integer not null default 0,
              source_extraction_id integer,
              demand_id integer,
              foreign key(project_key) references projects(key) on delete cascade
            )
            """
        )
        ensure_column(connection, "tasks", "demand_id", "integer")
        connection.execute(
            """
            create table if not exists risks (
              id integer primary key autoincrement,
              project_key text not null,
              title text not null,
              description text not null default '',
              probability text not null default '',
              impact text not null default '中',
              status text not null default '跟进中',
              response text not null default '',
              source_extraction_id integer,
              foreign key(project_key) references projects(key) on delete cascade
            )
            """
        )
        connection.execute(
            """
            create table if not exists demands (
              id integer primary key autoincrement,
              project_key text not null,
              title text not null,
              description text not null default '',
              status text not null default '待评估',
              scope_impact text not null default '',
              source_extraction_id integer,
              foreign key(project_key) references projects(key) on delete cascade
            )
            """
        )
        connection.execute(
            """
            create table if not exists milestones (
              id integer primary key autoincrement,
              project_key text not null,
              title text not null,
              date text not null default '',
              status text not null default '待开始',
              source_extraction_id integer,
              foreign key(project_key) references projects(key) on delete cascade
            )
            """
        )
        connection.execute(
            """
            create table if not exists project_gantt (
              project_key text primary key,
              rows_json text not null default '[]',
              updated_at text not null default current_timestamp,
              foreign key(project_key) references projects(key) on delete cascade
            )
            """
        )
        connection.execute(
            """
            create table if not exists snippets (
              id integer primary key autoincrement,
              project_key text not null,
              source_type text not null default 'meeting',
              raw_text text not null,
              extract_status text not null default 'pending',
              created_at text not null default current_timestamp,
              foreign key(project_key) references projects(key) on delete cascade
            )
            """
        )
        connection.execute(
            """
            create table if not exists extractions (
              id integer primary key autoincrement,
              snippet_id integer not null,
              project_key text not null,
              item_type text not null,
              title text not null,
              description text not null default '',
              owner text not null default '',
              due_date text not null default '',
              probability text not null default '',
              impact text not null default '',
              response text not null default '',
              status text not null default 'pending',
              target_table text not null default '',
              target_record_id integer,
              created_at text not null default current_timestamp,
              foreign key(snippet_id) references snippets(id) on delete cascade,
              foreign key(project_key) references projects(key) on delete cascade
            )
            """
        )
        connection.execute(
            """
            create table if not exists document_templates (
              id integer primary key autoincrement,
              name text not null,
              template_type text not null default 'srs',
              original_filename text not null default '',
              file_path text not null default '',
              status text not null default 'enabled',
              variables text not null default '',
              created_at text not null default current_timestamp,
              updated_at text not null default current_timestamp
            )
            """
        )
        connection.execute(
            """
            create table if not exists document_versions (
              id integer primary key autoincrement,
              project_key text not null,
              template_id integer not null,
              title text not null,
              content_markdown text not null,
              content_html text not null,
              version integer not null default 1,
              word_status text not null default 'not_exported',
              pdf_status text not null default 'not_started',
              lark_status text not null default 'not_synced',
              export_path text not null default '',
              created_at text not null default current_timestamp,
              foreign key(project_key) references projects(key) on delete cascade,
              foreign key(template_id) references document_templates(id) on delete cascade
            )
            """
        )
        connection.execute(
            """
            create table if not exists chat_messages (
              id integer primary key autoincrement,
              project_key text not null,
              view text not null default '',
              role text not null,
              content text not null,
              action_type text not null default '',
              action_payload text not null default '',
              created_at text not null default current_timestamp,
              foreign key(project_key) references projects(key) on delete cascade
            )
            """
        )
        seed_defaults(connection)
        connection.commit()
