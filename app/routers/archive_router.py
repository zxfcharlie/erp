import datetime
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from .. import models
from ..database import get_db
from ..auth import require_login

router = APIRouter(prefix="/order-archive")
templates = Jinja2Templates(directory="app/templates")


def visible_shops(user, db):
    if user.is_admin:
        return db.query(models.Shop).all()
    return user.shops


@router.get("", response_class=HTMLResponse)
def archive_list(
    request: Request,
    shop_id: Optional[int] = None,
    keyword: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    shops = visible_shops(user, db)
    shop_ids = [s.id for s in shops]
    q = db.query(models.OrderArchive)
    if not user.is_admin:
        q = q.filter(models.OrderArchive.shop_id.in_(shop_ids) if shop_ids else (models.OrderArchive.id == -1))
    if shop_id:
        q = q.filter(models.OrderArchive.shop_id == shop_id)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(
            (models.OrderArchive.order_no.ilike(like))
            | (models.OrderArchive.customer_order_number.ilike(like))
            | (models.OrderArchive.tracking_number.ilike(like))
        )
    if date_from:
        try:
            q = q.filter(models.OrderArchive.created_at >= datetime.datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(models.OrderArchive.created_at < datetime.datetime.strptime(date_to, "%Y-%m-%d") + datetime.timedelta(days=1))
        except ValueError:
            pass

    archives = q.order_by(models.OrderArchive.created_at.desc()).limit(300).all()
    total_archived = db.query(models.OrderArchive).count()
    filters = {"shop_id": shop_id, "keyword": keyword or "", "date_from": date_from or "", "date_to": date_to or ""}
    return templates.TemplateResponse(
        "order_archive_list.html",
        {"request": request, "user": user, "archives": archives, "shops": shops, "filters": filters, "total_archived": total_archived},
    )


@router.get("/{archive_id}", response_class=HTMLResponse)
def archive_detail(archive_id: int, request: Request, db: Session = Depends(get_db), user=Depends(require_login)):
    archive = db.query(models.OrderArchive).get(archive_id)
    if not archive or (not user.is_admin and archive.shop_id not in user.shop_ids):
        return RedirectResponse("/order-archive", status_code=303)
    data = archive.to_full_dict()
    import json as _json
    try:
        declared_items = _json.loads(data.get("declared_items_json") or "[]")
    except Exception:
        declared_items = []
    return templates.TemplateResponse(
        "order_archive_detail.html",
        {"request": request, "user": user, "archive": archive, "data": data, "declared_items": declared_items},
    )
