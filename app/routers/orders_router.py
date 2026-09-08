import datetime
import json
import uuid
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List, Optional
from .. import models
from ..database import get_db
from ..auth import require_login
from ..services.dispatcher import push_order as do_push_order

router = APIRouter(prefix="/orders")
templates = Jinja2Templates(directory="app/templates")


def visible_shops(user, db):
    if user.is_admin:
        return db.query(models.Shop).all()
    return user.shops


@router.get("", response_class=HTMLResponse)
def order_list(
    request: Request,
    shop_id: Optional[int] = None,
    status: Optional[str] = None,
    delivery_status: Optional[str] = None,
    review_status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    product_code: Optional[str] = None,
    customer_order_number: Optional[str] = None,
    tracking_number: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    shops = visible_shops(user, db)
    shop_ids = [s.id for s in shops]
    q = db.query(models.Order)
    if not user.is_admin:
        q = q.filter(models.Order.shop_id.in_(shop_ids) if shop_ids else (models.Order.id == -1))
    if shop_id:
        q = q.filter(models.Order.shop_id == shop_id)
    if status:
        q = q.filter(models.Order.status == status)
    if delivery_status:
        q = q.filter(models.Order.delivery_status == delivery_status)
    if review_status:
        q = q.filter(models.Order.review_status == review_status)
    if product_code:
        q = q.filter(models.Order.product_code.ilike(f"%{product_code}%"))
    if customer_order_number:
        q = q.filter(models.Order.customer_order_number.ilike(f"%{customer_order_number}%"))
    if tracking_number:
        q = q.filter(
            (models.Order.tracking_number.ilike(f"%{tracking_number}%"))
            | (models.Order.yunexpress_order_no.ilike(f"%{tracking_number}%"))
        )
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

    orders = q.order_by(models.Order.created_at.desc()).limit(300).all()
    filters = {
        "shop_id": shop_id, "status": status, "delivery_status": delivery_status,
        "date_from": date_from or "", "date_to": date_to or "",
        "product_code": product_code or "", "customer_order_number": customer_order_number or "",
        "tracking_number": tracking_number or "", "review_status": review_status,
    }
    return templates.TemplateResponse(
        "orders_list.html",
        {"request": request, "user": user, "orders": orders, "shops": shops, "filters": filters},
    )


@router.get("/new", response_class=HTMLResponse)
def order_new(request: Request, db: Session = Depends(get_db), user=Depends(require_login)):
    shops = visible_shops(user, db)
    providers = db.query(models.LogisticsProvider).filter(models.LogisticsProvider.is_active == True).all()  # noqa: E712
    declaration_templates = db.query(models.DeclarationItemTemplate).order_by(
        models.DeclarationItemTemplate.created_at.desc()
    ).limit(200).all()
    declaration_templates_json = json.dumps([t.to_dict() for t in declaration_templates], ensure_ascii=False)
    shops_sender_json = json.dumps(
        {s.id: s.sender_preset_dict() for s in shops}, ensure_ascii=False
    )
    return templates.TemplateResponse(
        "order_form.html",
        {
            "request": request, "user": user, "shops": shops, "providers": providers, "order": None,
            "declaration_templates_json": declaration_templates_json,
            "shops_sender_json": shops_sender_json,
        },
    )


@router.post("/new")
async def order_create(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    return await _save_order(request, db, user, order=None)


@router.get("/{order_id}/edit", response_class=HTMLResponse)
def order_edit(order_id: int, request: Request, db: Session = Depends(get_db), user=Depends(require_login)):
    order = db.query(models.Order).get(order_id)
    if not order or (not user.is_admin and order.shop_id not in user.shop_ids):
        return RedirectResponse("/orders", status_code=303)
    shops = visible_shops(user, db)
    providers = db.query(models.LogisticsProvider).filter(models.LogisticsProvider.is_active == True).all()  # noqa: E712
    declaration_templates = db.query(models.DeclarationItemTemplate).order_by(
        models.DeclarationItemTemplate.created_at.desc()
    ).limit(200).all()
    declaration_templates_json = json.dumps([t.to_dict() for t in declaration_templates], ensure_ascii=False)
    shops_sender_json = json.dumps(
        {s.id: s.sender_preset_dict() for s in shops}, ensure_ascii=False
    )
    return templates.TemplateResponse(
        "order_form.html",
        {
            "request": request, "user": user, "shops": shops, "providers": providers, "order": order,
            "declaration_templates_json": declaration_templates_json,
            "shops_sender_json": shops_sender_json,
        },
    )


@router.post("/{order_id}/edit")
async def order_edit_submit(order_id: int, request: Request, db: Session = Depends(get_db), user=Depends(require_login)):
    order = db.query(models.Order).get(order_id)
    if not order or (not user.is_admin and order.shop_id not in user.shop_ids):
        return RedirectResponse("/orders", status_code=303)
    return await _save_order(request, db, user, order=order)


@router.post("/{order_id}/approve")
def order_approve(order_id: int, db: Session = Depends(get_db), user=Depends(require_login)):
    """审核通过：外部系统推送进来的订单默认"待审核"，需要人工核对/补充物流信息后点这里才能推送云途"""
    order = db.query(models.Order).get(order_id)
    if not order or (not user.is_admin and order.shop_id not in user.shop_ids):
        return RedirectResponse("/orders", status_code=303)
    order.review_status = "approved"
    order.reviewed_by_name = user.real_name or user.username
    order.reviewed_at = datetime.datetime.utcnow()
    db.commit()
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


@router.get("/{order_id}", response_class=HTMLResponse)
def order_detail(order_id: int, request: Request, db: Session = Depends(get_db), user=Depends(require_login)):
    order = db.query(models.Order).get(order_id)
    if not order or (not user.is_admin and order.shop_id not in user.shop_ids):
        return RedirectResponse("/orders", status_code=303)
    providers = db.query(models.LogisticsProvider).filter(models.LogisticsProvider.is_active == True).all()  # noqa: E712
    return templates.TemplateResponse(
        "order_detail.html", {"request": request, "user": user, "order": order, "providers": providers}
    )


@router.post("/{order_id}/push")
def order_push(order_id: int, provider_id: int = Form(...), db: Session = Depends(get_db), user=Depends(require_login)):
    order = db.query(models.Order).get(order_id)
    if not order or (not user.is_admin and order.shop_id not in user.shop_ids):
        return RedirectResponse("/orders", status_code=303)
    if order.review_status == "pending":
        order.push_error = "该订单还待审核，请先完成审核（补充物流信息后点\"审核通过\"）再推送"
        db.commit()
        return RedirectResponse(f"/orders/{order_id}", status_code=303)
    provider = db.query(models.LogisticsProvider).get(provider_id)
    if not provider:
        order.push_error = "未选择有效的物流商配置"
        db.commit()
        return RedirectResponse(f"/orders/{order_id}", status_code=303)

    result = do_push_order(provider, order)
    order.logistics_provider_id = provider.id
    order.push_response = result.get("raw_response", "")
    order.push_error = result.get("error", "")
    if result.get("success"):
        order.status = "success"
        order.tracking_number = result.get("tracking_number") or order.tracking_number
        order.yunexpress_order_no = result.get("ye_order_no") or order.yunexpress_order_no
    else:
        order.status = "failed"
    db.commit()
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


@router.post("/{order_id}/refresh-tracking")
def order_refresh_tracking(order_id: int, db: Session = Depends(get_db), user=Depends(require_login)):
    """手动刷新该订单的实际运费/重量/签收状态(调用云途费用详情+全程轨迹接口)"""
    from ..services.sync import refresh_order_tracking
    order = db.query(models.Order).get(order_id)
    if not order or (not user.is_admin and order.shop_id not in user.shop_ids):
        return RedirectResponse("/orders", status_code=303)
    refresh_order_tracking(db, order)
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


@router.post("/{order_id}/set-freight")
def order_set_freight(
    order_id: int,
    actual_freight: str = Form(""),
    freight_currency: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(require_login),
):
    """手动录入实际物流运费(云途运费查询没有数据时的兜底方式)"""
    order = db.query(models.Order).get(order_id)
    if not order or (not user.is_admin and order.shop_id not in user.shop_ids):
        return RedirectResponse("/orders", status_code=303)
    order.actual_freight = float(actual_freight) if actual_freight else None
    if freight_currency:
        order.freight_currency = freight_currency
    db.commit()
    return RedirectResponse(f"/orders/{order_id}", status_code=303)


def _f(form, key, default=""):
    return form.get(key, default)


async def _save_order(request: Request, db: Session, user, order):
    form = await request.form()
    is_new = order is None
    if is_new:
        order = models.Order(order_no=f"SO{datetime.datetime.utcnow():%Y%m%d%H%M%S}{uuid.uuid4().hex[:5].upper()}")
        order.created_by_id = user.id
        order.created_by_name = user.real_name or user.username
        order.created_at = datetime.datetime.utcnow()
        order.source = "web"
        order.review_status = "approved"

    shop_id = int(form.get("shop_id"))
    if not user.is_admin and shop_id not in user.shop_ids:
        return RedirectResponse("/orders", status_code=303)
    order.shop_id = shop_id

    order.customer_order_number = _f(form, "customer_order_number")
    order.product_name = _f(form, "product_name")
    order.order_amount = float(form.get("order_amount") or 0)
    order.actual_received_amount = float(form.get("actual_received_amount") or 0)
    order.purchase_cost_rmb = float(form.get("purchase_cost_rmb") or 0)

    order.product_code = _f(form, "product_code")
    order.additional_service = _f(form, "additional_service")
    order.insurance_service = form.get("insurance_service") == "on"
    order.insurance_amount = float(form.get("insurance_amount") or 0)
    order.signature_service = form.get("signature_service") == "on"
    order.vat_number = _f(form, "vat_number")
    order.eu_tax_number = _f(form, "eu_tax_number")
    order.ioss_number = _f(form, "ioss_number")
    order.production_sales_unit = _f(form, "production_sales_unit")
    order.uscc = _f(form, "uscc")
    order.cod_flag = _f(form, "cod_flag")
    order.cargo_type = _f(form, "cargo_type")

    order.receiver_country = _f(form, "receiver_country")
    order.receiver_name = _f(form, "receiver_name")
    order.receiver_id_number = _f(form, "receiver_id_number")
    order.receiver_company = _f(form, "receiver_company")
    order.receiver_address = _f(form, "receiver_address")
    order.receiver_city = _f(form, "receiver_city")
    order.receiver_state = _f(form, "receiver_state")
    order.receiver_zip = _f(form, "receiver_zip")
    order.receiver_phone = _f(form, "receiver_phone")
    order.receiver_house_number = _f(form, "receiver_house_number")
    order.receiver_email = _f(form, "receiver_email")
    order.receiver_short_address = _f(form, "receiver_short_address")

    order.package_count = int(form.get("package_count") or 1)
    order.total_weight = float(form.get("total_weight") or 0)
    order.package_length = float(form.get("package_length") or 0)
    order.package_width = float(form.get("package_width") or 0)
    order.package_height = float(form.get("package_height") or 0)

    order.sender_name = _f(form, "sender_name")
    order.sender_company = _f(form, "sender_company")
    order.sender_address = _f(form, "sender_address")
    order.sender_city = _f(form, "sender_city")
    order.sender_state = _f(form, "sender_state")
    order.sender_zip = _f(form, "sender_zip")
    order.sender_country = _f(form, "sender_country")
    order.sender_phone = _f(form, "sender_phone")
    order.sender_email = _f(form, "sender_email")
    order.sender_usci = _f(form, "sender_usci")

    order.platform_name = _f(form, "platform_name")
    order.platform_address = _f(form, "platform_address")
    order.platform_state = _f(form, "platform_state")
    order.platform_zip = _f(form, "platform_zip")
    order.platform_phone = _f(form, "platform_phone")
    order.platform_email = _f(form, "platform_email")
    order.platform_code = _f(form, "platform_code")
    order.platform_sales_link = _f(form, "platform_sales_link")

    order.declare_currency = _f(form, "declare_currency", "USD")

    order.payment_platform = _f(form, "payment_platform")
    order.payment_account = _f(form, "payment_account")
    order.payment_transaction_no = _f(form, "payment_transaction_no")

    # 申报品名(可多行): 字段名形如 item_sku[]、item_name_en[] 等，通过 form.getlist 获取
    skus = form.getlist("item_sku")
    names_en = form.getlist("item_name_en")
    names_cn = form.getlist("item_name_cn")
    qtys = form.getlist("item_qty")
    fob = form.getlist("item_fob")
    price = form.getlist("item_price")
    unit_weight = form.getlist("item_unit_weight")
    hs_code = form.getlist("item_hs_code")
    material = form.getlist("item_material")
    brand = form.getlist("item_brand")

    items = []
    for i in range(len(names_en)):
        if not (names_en[i] if i < len(names_en) else "").strip():
            continue
        items.append({
            "sku": skus[i] if i < len(skus) else "",
            "declared_name_en": names_en[i] if i < len(names_en) else "",
            "declared_name_cn": names_cn[i] if i < len(names_cn) else "",
            "quantity": qtys[i] if i < len(qtys) else "",
            "declared_fob": fob[i] if i < len(fob) else "",
            "transaction_price": price[i] if i < len(price) else "",
            "unit_weight": unit_weight[i] if i < len(unit_weight) else "",
            "hs_code": hs_code[i] if i < len(hs_code) else "",
            "material": material[i] if i < len(material) else "",
            "brand": brand[i] if i < len(brand) else "",
        })
    order.set_declared_items(items)

    if is_new:
        db.add(order)
    db.commit()
    return RedirectResponse(f"/orders/{order.id}", status_code=303)
