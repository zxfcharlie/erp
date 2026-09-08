import datetime
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
from .. import models
from ..database import get_db
from ..auth import require_login

router = APIRouter(prefix="/reports")
templates = Jinja2Templates(directory="app/templates")


def visible_shops(user, db):
    if user.is_admin:
        return db.query(models.Shop).all()
    return user.shops


@router.get("/profit", response_class=HTMLResponse)
def profit_report(
    request: Request,
    shop_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    """
    利润统计：基础利润 = 实收金额 - 采购成本(人民币)；最终利润 = 基础利润 - 实际物流运费。
    实际物流运费来自订单详情页"刷新物流状态"(调云途运费查询接口)或手动录入；
    没有运费数据的订单，最终利润显示为"-"（不用 0 顶替，避免统计失真）。
    """
    shops = visible_shops(user, db)
    shop_ids = [s.id for s in shops]
    q = db.query(models.Order)
    if not user.is_admin:
        q = q.filter(models.Order.shop_id.in_(shop_ids) if shop_ids else (models.Order.id == -1))
    if shop_id:
        q = q.filter(models.Order.shop_id == shop_id)
    if date_from:
        try:
            q = q.filter(models.Order.created_at >= datetime.datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(models.Order.created_at < datetime.datetime.strptime(date_to, "%Y-%m-%d") + datetime.timedelta(days=1))
        except ValueError:
            pass
    orders = q.order_by(models.Order.created_at.desc()).limit(1000).all()

    rows = []
    totals = {
        "order_amount": 0.0, "actual_received_amount": 0.0, "purchase_cost_rmb": 0.0,
        "actual_freight": 0.0, "base_profit": 0.0, "final_profit": 0.0, "final_profit_count": 0,
    }
    for o in orders:
        base_profit = (o.actual_received_amount or 0) - (o.purchase_cost_rmb or 0)
        has_freight = o.actual_freight is not None
        final_profit = base_profit - (o.actual_freight or 0) if has_freight else None
        rows.append({"order": o, "base_profit": base_profit, "final_profit": final_profit, "has_freight": has_freight})
        totals["order_amount"] += o.order_amount or 0
        totals["actual_received_amount"] += o.actual_received_amount or 0
        totals["purchase_cost_rmb"] += o.purchase_cost_rmb or 0
        totals["base_profit"] += base_profit
        if has_freight:
            totals["actual_freight"] += o.actual_freight or 0
            totals["final_profit"] += final_profit
            totals["final_profit_count"] += 1

    filters = {"shop_id": shop_id, "date_from": date_from or "", "date_to": date_to or ""}
    return templates.TemplateResponse(
        "profit_report.html",
        {"request": request, "user": user, "shops": shops, "rows": rows, "totals": totals, "filters": filters},
    )
