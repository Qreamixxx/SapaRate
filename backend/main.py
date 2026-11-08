"""HTTP API + serves the frontend. Run:  python run.py   (or: uvicorn backend.main:app --reload)"""
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import service, settings, storage
from .llm import LLMError

app = FastAPI(title="SapaRate — Conversation Quality Analytics")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
service.bootstrap()


@app.exception_handler(service.NotFound)
async def _not_found(_: Request, exc: Exception):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(ValueError)
async def _bad_request(_: Request, exc: Exception):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(LLMError)
async def _llm_error(_: Request, exc: Exception):
    return JSONResponse({"detail": f"Ошибка модели: {exc}"}, status_code=502)


# ---------- request bodies ----------
class GroupFetch(BaseModel):
    group_id: str


class GroupUpload(BaseModel):
    group_id: str
    payload: Any


class ChecklistSave(BaseModel):
    checklist_id: str
    data: dict


class EvaluateReq(BaseModel):
    conversation_id: str
    checklist_id: str
    version: Optional[int] = None


class BatchReq(BaseModel):
    checklist_id: str
    version: Optional[int] = None
    group_id: Optional[str] = None
    conversation_ids: Optional[list[str]] = None
    only_missing: bool = False
    dry_run: bool = False   # only count how many model requests the batch would make


class AppealReq(BaseModel):
    evaluation_id: str
    criterion_id: str
    comment: str


class DecisionReq(BaseModel):
    action: str
    answer: Optional[str] = None
    value: Optional[float] = None
    reason: str


# ---------- routes ----------
@app.get("/api/health")
def health():
    return {"ok": True, **service.stats(), "data_api": bool(settings.DATA_API_URL)}


@app.get("/api/stats")
def stats():
    return service.stats()


@app.get("/api/groups")
def groups():
    return storage.list_groups()


@app.post("/api/groups/fetch")
def fetch_group(body: GroupFetch):
    return service.load_group(body.group_id.strip())


@app.post("/api/groups/upload")
def upload_group(body: GroupUpload):
    return service.upload_group(body.group_id.strip(), body.payload)


@app.get("/api/conversations")
def conversations(group_id: Optional[str] = None):
    return service.list_conversations(group_id or None)


@app.get("/api/conversations/{conversation_id}")
def conversation(conversation_id: str):
    return service.get_conversation(conversation_id)


@app.get("/api/conversations/{conversation_id}/audio")
def conversation_audio(conversation_id: str):
    return service.audio_src(conversation_id)


@app.get("/api/conversations/{conversation_id}/evaluations")
def conversation_evaluations(conversation_id: str):
    return service.evaluations_for(conversation_id)


@app.get("/api/checklists")
def checklists():
    return storage.list_checklists()


@app.get("/api/checklists/{checklist_id}")
def checklist(checklist_id: str, version: Optional[int] = None):
    return service.get_checklist(checklist_id, version)


@app.post("/api/checklists")
def save_checklist(body: ChecklistSave):
    return service.save_checklist(body.checklist_id, body.data)


@app.post("/api/evaluations")
def evaluate(body: EvaluateReq):
    return service.evaluate_conversation(body.conversation_id, body.checklist_id, body.version)


@app.get("/api/evaluations/{evaluation_id}")
def evaluation(evaluation_id: str):
    return service.get_evaluation(evaluation_id)


@app.post("/api/batches")
def batch(body: BatchReq):
    return service.start_batch(body.checklist_id, body.version, body.group_id, body.conversation_ids,
                               body.only_missing, body.dry_run)


@app.get("/api/batches/{job_id}")
def batch_status(job_id: str):
    return service.get_job(job_id)


@app.get("/api/compare")
def compare(checklist_id: str, a: int, b: int, group_id: Optional[str] = None):
    return service.compare_versions(checklist_id, a, b, group_id or None)


@app.get("/api/summary")
def summary(group_id: Optional[str] = None):
    return service.summary(group_id or None)


@app.get("/api/appeals")
def appeals(status: Optional[str] = None, evaluation_id: Optional[str] = None):
    return service.list_appeals(status, evaluation_id)


@app.post("/api/appeals")
def create_appeal(body: AppealReq):
    return service.create_appeal(body.evaluation_id, body.criterion_id, body.comment)


@app.post("/api/appeals/{appeal_id}/decision")
def decide(appeal_id: str, body: DecisionReq):
    return service.decide_appeal(appeal_id, body.action, body.answer, body.value, body.reason)


# frontend (must be last so it does not shadow /api)
app.mount("/", StaticFiles(directory=settings.ROOT / "frontend", html=True), name="frontend")
