from fastapi import APIRouter, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from typing import Literal
from .followup_reports import FollowupReportService
from .evaluations import EvaluationService
from .workflow import WorkflowService, WorkflowSetup, WorkflowAutomation
from .models import FollowupReportRequest, EvaluationRequest
from fastapi.exception_handlers import request_validation_exception_handler

from .ai.jobs import JobService
from .ai.worker import AnalysisWorker
from .ai.client import DeepSeekClient
from .ai.settings import AISettingsStore, AISettingsUpdate
from .imports import ImportService
from .models import AnalysisPreview, AnalysisEnqueue, AutomationUpdate, ProposalApply, BatchProposalAction, ItemLifecycle, ItemMerge, ImportCommit, ImportPreview, ProjectCreate, SourceBind, WorkItemCreate, WorkItemUpdate
from .work_items import DeliveryError, WorkItemService


def install_delivery_api(app, database, organizer):
    delivery = WorkItemService(database)
    imports = ImportService(database,organizer)
    store = AISettingsStore(database.path)
    ai = DeepSeekClient(store,database)
    app.state.delivery, app.state.imports, app.state.ai_store, app.state.ai_client = delivery,imports,store,ai
    jobs = JobService(database,store)
    app.state.ai_jobs, app.state.ai_worker = jobs, AnalysisWorker(database,jobs,ai)
    reports, evaluations = FollowupReportService(database), EvaluationService(database)
    app.state.followup_reports, app.state.evaluations = reports, evaluations
    workflow = WorkflowService(database,delivery,store)
    router = APIRouter(prefix='/api')

    @router.get('/workflow/status')
    def workflow_status(project_id: int | None = Query(None,ge=1)):
        return workflow.status(project_id)

    @router.put('/workflow/setup')
    def workflow_setup(data: WorkflowSetup):
        return workflow.setup(data)

    @router.put('/workflow/automation')
    def workflow_automation(data: WorkflowAutomation):
        return workflow.automation(data)

    @app.exception_handler(DeliveryError)
    async def delivery_error(request, exc):
        return JSONResponse(status_code=exc.status,content={'code':exc.code,'detail':exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path == '/api/ai/settings':
            # FastAPI normally includes invalid input values. Never echo an API key.
            return JSONResponse(status_code=422,content={'code':'invalid_settings','detail':'模型配置格式不合法，请检查模型 ID、地址和数值范围'})
        if request.url.path == '/api/evaluations':
            return JSONResponse(status_code=422,content={'code':'invalid_evaluation','detail':'评测字段不合法，请检查样本来源、标注、确认勾选和有限用时数值'})
        return await request_validation_exception_handler(request,exc)

    @router.get('/projects')
    def projects():
        return delivery.projects()

    @router.post('/projects',status_code=201)
    def create_project(data: ProjectCreate):
        return delivery.create_project(data)

    @router.put('/projects/{project_id}/sources')
    def bind_source(project_id: int, data: SourceBind):
        return delivery.bind_source(project_id,data)

    @router.post('/imports/preview')
    def preview(data: ImportPreview):
        return imports.preview(data)

    @router.post('/imports/{batch_id}/commit')
    def commit(batch_id: int, data: ImportCommit):
        return imports.commit(batch_id,data.accept_valid_rows)

    @router.get('/work-items')
    def items(project_id: int | None = Query(None,ge=1),review_status: str | None = Query(None,pattern='^(pending|confirmed|ignored)$'),work_status: str | None = Query(None,pattern='^(open|in_progress|waiting_confirmation|resolved)$'),page: int = Query(1,ge=1),page_size: int = Query(20,ge=1,le=100), withdrawn: bool = Query(False)):
        return delivery.list_items(project_id,review_status,work_status,page,page_size,withdrawn)

    @router.post('/work-items',status_code=201)
    def create_item(data: WorkItemCreate):
        return delivery.create_item(data)

    @router.get('/work-items/{item_id}/evidence')
    def evidence(item_id: int):
        return delivery.evidence(item_id)

    @router.patch('/work-items/{item_id}')
    def update_item(item_id: int,data: WorkItemUpdate):
        return delivery.update_item(item_id,data)

    @router.delete('/work-items/{item_id}')
    def withdraw_item(item_id: int,data: ItemLifecycle):
        return delivery.set_withdrawn(item_id,data.expected_version,True)

    @router.post('/work-items/{item_id}/restore')
    def restore_item(item_id: int,data: ItemLifecycle):
        return delivery.set_withdrawn(item_id,data.expected_version,False)

    @router.get('/ai/settings')
    def ai_settings():
        return store.public()

    @router.put('/ai/settings')
    def save_ai(data: AISettingsUpdate):
        return store.save(data)

    @router.post('/ai/test')
    async def test_ai():
        return await ai.connection_test()

    @router.post('/ai/jobs/preview')
    def analysis_preview(data: AnalysisPreview):
        return jobs.preview(data)

    @router.post('/ai/jobs',status_code=202)
    def enqueue_analysis(data: AnalysisEnqueue):
        return jobs.enqueue(data)

    @router.get('/ai/jobs')
    def list_jobs(project_id: int | None = Query(None,ge=1)):
        return jobs.list(project_id)

    @router.get('/ai/jobs/{job_id}')
    def get_job(job_id: int):
        return jobs.get(job_id)

    @router.post('/ai/jobs/{job_id}/retry')
    def retry_job(job_id: int):
        return jobs.action(job_id,'retry')

    @router.post('/ai/jobs/{job_id}/cancel')
    def cancel_job(job_id: int):
        return jobs.action(job_id,'cancel')

    @router.put('/sources/{source_id}/automation')
    def automation(source_id: int,data: AutomationUpdate):
        return jobs.automation(source_id,data)

    @router.get('/item-proposals')
    def proposals(project_id: int | None = Query(None,ge=1), page: int = Query(1,ge=1), page_size: int = Query(100,ge=1,le=100), item_type: Literal['issue','task','decision','risk'] | None = Query(None,alias='type')):
        return delivery.proposals(project_id,page,page_size,item_type)

    @router.get('/item-proposals/{proposal_id}/evidence')
    def proposal_evidence(proposal_id: int):
        return delivery.proposal_evidence(proposal_id)

    @router.post('/item-proposals/batch')
    def batch_proposals(data: BatchProposalAction):
        return delivery.batch_proposals(data)

    @router.post('/item-proposals/{proposal_id}/apply')
    def apply_proposal(proposal_id: int,data: ProposalApply):
        return delivery.apply_proposal(proposal_id,data)

    @router.post('/item-proposals/{proposal_id}/dismiss')
    def dismiss_proposal(proposal_id: int):
        return delivery.dismiss_proposal(proposal_id)

    @router.post('/work-items/{item_id}/merge')
    def merge_item(item_id: int,data: ItemMerge):
        return delivery.merge_items(item_id,data)

    @router.post('/followup-reports')
    def generate_followup(data: FollowupReportRequest):
        return reports.generate(data)

    @router.get('/followup-reports')
    def list_followups(project_id: int | None = Query(None,ge=1)):
        return reports.list(project_id)

    @router.get('/followup-reports/{report_id}')
    def get_followup(report_id: int):
        return reports.get(report_id)

    @router.get('/followup-reports/{report_id}/export')
    def export_followup(report_id: int, format: Literal['markdown','csv']='markdown'):
        content, media, extension=reports.export(report_id,format)
        return Response(content,media_type=media,headers={'Content-Disposition':f'attachment; filename="followup-{report_id}.{extension}"'})

    @router.get('/evaluations/inputs')
    def evaluation_inputs(project_id: int = Query(ge=1)):
        return evaluations.inputs(project_id)

    @router.post('/evaluations')
    def evaluate(data: EvaluationRequest):
        return evaluations.create(data)

    @router.get('/evaluations')
    def list_evaluations(project_id: int | None = Query(None,ge=1)):
        return evaluations.list(project_id)

    @router.get('/evaluations/{evaluation_id}')
    def get_evaluation(evaluation_id: int):
        return evaluations.get(evaluation_id)

    @router.get('/evaluations/{evaluation_id}/export')
    def export_evaluation(evaluation_id: int):
        return Response(evaluations.export(evaluation_id),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="evaluation-{evaluation_id}.csv"'})

    app.include_router(router)
