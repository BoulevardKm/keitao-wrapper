from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.errors import AppError
from app.keitaro import KeitaroClient, KeitaroError
from app.models import CampaignRecord
from app.services.creator import CampaignCreator
from app.services.editor import StreamEditor

router = APIRouter()
templates = Jinja2Templates(directory=str(settings.templates_dir))

OK_TEXT = {
    "created": "Кампания создана, потоки загружены из Keitaro.",
    "opened": "Кампания загружена из Keitaro.",
    "fetched": "Потоки заново прочитаны из Keitaro. Неопубликованные правки сброшены.",
    "added": "Оффер добавлен. Поток ещё не опубликован.",
    "removed": "Оффер убран в архив. Поток ещё не опубликован.",
    "restored": "Оффер возвращён. Поток ещё не опубликован.",
    "pinned": "Пин обновлён. Доля зафиксирована для следующих пересчётов.",
    "pushed": "Поток опубликован в Keitaro.",
    "cancelled": "Неопубликованные изменения отменены.",
}


def services(db: Session = Depends(get_db)) -> dict:
    client = KeitaroClient(settings)
    return {
        "db": db,
        "client": client,
        "creator": CampaignCreator(client, settings),
        "editor": StreamEditor(client, db),
    }


def _redirect(url: str, **query: str) -> RedirectResponse:
    pairs = {key: value for key, value in query.items() if value}
    target = url if not pairs else f"{url}?{urlencode(pairs)}"
    return RedirectResponse(target, status_code=303)


def _editor_url(keitaro_id: int) -> str:
    return f"/campaigns/{keitaro_id}"


def _fail(url: str, exc: Exception) -> RedirectResponse:
    return _redirect(url, error=str(exc))


def _offer_id(raw: str) -> int:
    text = raw.strip()
    if not text.isdigit():
        raise AppError("Укажите id оффера.")
    return int(text)


def _tracking_url(campaign: CampaignRecord) -> str | None:
    if not campaign.domain_name or not campaign.alias:
        return None
    host = campaign.domain_name
    if not host.startswith("http://") and not host.startswith("https://"):
        host = "https://" + host
    return host.rstrip("/") + "/" + campaign.alias


@router.get("/")
def home(request: Request, bag: dict = Depends(services)):
    editor: StreamEditor = bag["editor"]
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "campaigns": editor.list_campaigns(),
            "error": request.query_params.get("error", ""),
            "ok": OK_TEXT.get(request.query_params.get("ok", ""), ""),
            "domain": settings.keitaro_domain,
            "group": settings.keitaro_group,
            "source": settings.keitaro_source,
        },
    )


@router.post("/campaigns")
def create_campaign(
    name: str = Form(""),
    geo: str = Form(""),
    offer_id: str = Form(""),
    bag: dict = Depends(services),
):
    creator: CampaignCreator = bag["creator"]
    editor: StreamEditor = bag["editor"]
    try:
        campaign = creator.create(name, geo, _offer_id(offer_id))
        editor.fetch(str(campaign["id"]))
    except (AppError, KeitaroError) as exc:
        return _fail("/", exc)
    return _redirect(_editor_url(int(campaign["id"])), ok="created")


@router.post("/campaigns/open")
def open_campaign(campaign: str = Form(""), bag: dict = Depends(services)):
    editor: StreamEditor = bag["editor"]
    try:
        record = editor.fetch(campaign)
    except (AppError, KeitaroError) as exc:
        return _fail("/", exc)
    return _redirect(_editor_url(record.keitaro_id), ok="opened")


@router.get("/campaigns/{keitaro_id}")
def editor_page(keitaro_id: int, request: Request, bag: dict = Depends(services)):
    editor: StreamEditor = bag["editor"]
    campaign = editor.get_campaign(keitaro_id)
    streams = sorted(campaign.streams, key=lambda stream: (stream.position, stream.id)) if campaign else []
    return templates.TemplateResponse(
        request,
        "editor.html",
        {
            "campaign": campaign,
            "keitaro_id": keitaro_id,
            "streams": streams,
            "tracking_url": _tracking_url(campaign) if campaign else None,
            "error": request.query_params.get("error", ""),
            "ok": OK_TEXT.get(request.query_params.get("ok", ""), ""),
            "dirty": any(stream.dirty for stream in streams),
        },
    )


@router.post("/campaigns/{keitaro_id}/fetch")
def fetch_campaign(keitaro_id: int, bag: dict = Depends(services)):
    editor: StreamEditor = bag["editor"]
    url = _editor_url(keitaro_id)
    try:
        editor.fetch(str(keitaro_id))
    except (AppError, KeitaroError) as exc:
        return _fail(url, exc)
    return _redirect(url, ok="fetched")


@router.post("/campaigns/{keitaro_id}/streams/{stream_id}/offers")
def add_offer(keitaro_id: int, stream_id: int, offer_id: str = Form(""), bag: dict = Depends(services)):
    editor: StreamEditor = bag["editor"]
    url = _editor_url(keitaro_id)
    try:
        editor.add_offer(keitaro_id, stream_id, _offer_id(offer_id))
    except (AppError, KeitaroError) as exc:
        return _fail(url, exc)
    return _redirect(url, ok="added")


@router.post("/campaigns/{keitaro_id}/streams/{stream_id}/offers/{binding_id}/remove")
def remove_offer(keitaro_id: int, stream_id: int, binding_id: int, bag: dict = Depends(services)):
    return _stream_action(bag, keitaro_id, "removed", lambda editor: editor.remove_offer(keitaro_id, stream_id, binding_id))


@router.post("/campaigns/{keitaro_id}/streams/{stream_id}/offers/{binding_id}/restore")
def restore_offer(keitaro_id: int, stream_id: int, binding_id: int, bag: dict = Depends(services)):
    return _stream_action(bag, keitaro_id, "restored", lambda editor: editor.restore_offer(keitaro_id, stream_id, binding_id))


@router.post("/campaigns/{keitaro_id}/streams/{stream_id}/offers/{binding_id}/pin")
def pin_offer(
    keitaro_id: int,
    stream_id: int,
    binding_id: int,
    pinned: str = Form("1"),
    bag: dict = Depends(services),
):
    return _stream_action(
        bag,
        keitaro_id,
        "pinned",
        lambda editor: editor.set_pin(keitaro_id, stream_id, binding_id, pinned == "1"),
    )


@router.post("/campaigns/{keitaro_id}/streams/{stream_id}/push")
def push_stream(keitaro_id: int, stream_id: int, bag: dict = Depends(services)):
    return _stream_action(bag, keitaro_id, "pushed", lambda editor: editor.push(keitaro_id, stream_id))


@router.post("/campaigns/{keitaro_id}/streams/{stream_id}/cancel")
def cancel_stream(keitaro_id: int, stream_id: int, bag: dict = Depends(services)):
    return _stream_action(bag, keitaro_id, "cancelled", lambda editor: editor.cancel(keitaro_id, stream_id))


@router.get("/api/offers")
def search_offers(q: str = "", bag: dict = Depends(services)):
    try:
        return bag["client"].search_offers(q)
    except (AppError, KeitaroError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


def _stream_action(bag: dict, keitaro_id: int, ok: str, action) -> RedirectResponse:
    url = _editor_url(keitaro_id)
    try:
        action(bag["editor"])
    except (AppError, KeitaroError) as exc:
        return _fail(url, exc)
    return _redirect(url, ok=ok)
