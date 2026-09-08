from fastapi import APIRouter, Request, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
import datetime
import uuid
from .. import models
from ..database import get_db
from ..auth import require_login

router = APIRouter(prefix="/api")


@router.get("/product-codes/search")
def search_product_codes(q: str = "", db: Session = Depends(get_db), user=Depends(require_login)):
    """
    产品代码搜索(本地库)。
    TODO: 待云途"查询物流产品列表"接口文档确认后，可在这里改为调用真实接口，
    或者定时把云途产品同步到 product_codes 表里，前端搜索逻辑不用改。
    """
    query = db.query(models.ProductCode)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (models.ProductCode.code.ilike(like)) | (models.ProductCode.name.ilike(like))
        )
    items = query.order_by(models.ProductCode.code).limit(20).all()
    return JSONResponse([
        {"code": p.code, "name": p.name, "remark": p.remark} for p in items
    ])


@router.get("/declaration-templates")
def list_declaration_templates(db: Session = Depends(get_db), user=Depends(require_login)):
    items = db.query(models.DeclarationItemTemplate).order_by(
        models.DeclarationItemTemplate.created_at.desc()
    ).limit(200).all()
    return JSONResponse([t.to_dict() for t in items])


@router.post("/declaration-templates")
async def save_declaration_template(request: Request, db: Session = Depends(get_db), user=Depends(require_login)):
    body = await request.json()

    def _f(key, default=""):
        return body.get(key, default)

    name_en = (_f("declared_name_en") or "").strip()
    if not name_en:
        return JSONResponse({"success": False, "error": "英文品名不能为空"}, status_code=400)

    tpl = models.DeclarationItemTemplate(
        label=name_en,
        sku=_f("sku"),
        declared_name_en=name_en,
        declared_name_cn=_f("declared_name_cn"),
        quantity=float(_f("quantity", 1) or 1),
        declared_fob=float(_f("declared_fob", 0) or 0),
        unit_weight=float(_f("unit_weight", 0) or 0),
        hs_code=_f("hs_code"),
        material=_f("material"),
        brand=_f("brand"),
        created_by_id=user.id,
    )
    db.add(tpl)
    db.commit()
    return JSONResponse({"success": True, "template": tpl.to_dict()})


@router.post("/shops/{shop_id}/sender-preset")
async def save_shop_sender_preset(shop_id: int, request: Request, db: Session = Depends(get_db), user=Depends(require_login)):
    """把当前填写的发件人信息保存为该店铺的默认预设，下次新建订单选中该店铺自动填充"""
    shop = db.query(models.Shop).get(shop_id)
    if not shop:
        return JSONResponse({"success": False, "error": "店铺不存在"}, status_code=404)
    if not user.is_admin and shop_id not in user.shop_ids:
        return JSONResponse({"success": False, "error": "无权限操作该店铺"}, status_code=403)

    body = await request.json()
    shop.sender_name = body.get("sender_name", "")
    shop.sender_country = body.get("sender_country", "")
    shop.sender_state = body.get("sender_state", "")
    shop.sender_city = body.get("sender_city", "")
    shop.sender_address = body.get("sender_address", "")
    shop.sender_zip = body.get("sender_zip", "")
    shop.sender_phone = body.get("sender_phone", "")
    db.commit()
    return JSONResponse({"success": True, "preset": shop.sender_preset_dict()})


# =====================================================================
# 外部系统推送订单接口 (使用店铺 API Key 鉴权，不依赖登录会话)
# 用法见 README.md「外部推送订单接口」章节
# =====================================================================

def _require(errors: list, container: dict, key: str, path: str):
    v = container.get(key)
    empty = v is None or (isinstance(v, str) and not v.strip())
    if empty:
        errors.append(path)
    return v


@router.post("/external/orders")
async def external_create_order(
    request: Request,
    db: Session = Depends(get_db),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """
    外部系统创建发货订单接口。
    Header: X-API-Key: <店铺的外部推送API密钥>（在"店铺管理"页面查看/生成）
    Body(JSON): 见 README「外部推送订单接口」章节的字段说明和示例。

    只需要传业务信息(订单金额/实收/采购成本)+商品名称+收件人+发件人，不需要传产品代码/包裹/申报品名
    这些物流细节——这些字段留空即可，订单会以"待审核"状态创建，由 ERP 里的人工在审核时
    补充这些信息，审核通过后才能推送云途（成功返回 201，状态固定是 "draft" + 待审核，
    不会自动推送，所以不再支持/无需传 auto_push）。
    商品名称(product_name)是必填的，作为人工审核时填写"申报品名"的参考，本身不会直接
    传给云途(申报品名走的是英文/中文报关品名 items 字段，两者概念不同)。
    """
    shop = db.query(models.Shop).filter(models.Shop.api_key == x_api_key).first() if x_api_key else None
    if not shop:
        return JSONResponse({"success": False, "error": "无效的 X-API-Key"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "请求体不是合法 JSON"}, status_code=400)

    errors = []
    order_amount = _require(errors, body, "order_amount", "order_amount")
    actual_received_amount = _require(errors, body, "actual_received_amount", "actual_received_amount")
    purchase_cost_rmb = _require(errors, body, "purchase_cost_rmb", "purchase_cost_rmb")
    product_name = _require(errors, body, "product_name", "product_name")

    receiver = body.get("receiver") or {}
    for k in ["country", "name", "house_number", "state", "zip", "address", "city", "phone"]:
        _require(errors, receiver, k, f"receiver.{k}")

    # 物流细节字段(产品代码/包裹/申报品名)不再要求外部系统传，留给人工审核时补充
    package = body.get("package") or {}
    items = body.get("items") or []

    # 发件人：请求里没给全，就用该店铺保存过的默认发件人预设兜底
    sender = body.get("sender") or {}
    sender_keys = ["name", "country", "state", "city", "address", "zip", "phone"]
    sender_complete = all((sender.get(k) or "").strip() for k in sender_keys)
    if not sender_complete:
        preset = shop.sender_preset_dict()
        if preset.get("sender_name"):
            sender = {
                "name": preset["sender_name"], "country": preset["sender_country"],
                "state": preset["sender_state"], "city": preset["sender_city"],
                "address": preset["sender_address"], "zip": preset["sender_zip"],
                "phone": preset["sender_phone"],
            }
        else:
            errors.append("sender(未提供，且该店铺还没有保存过默认发件人预设，请先在ERP里保存一次或在请求里带上完整sender)")

    if errors:
        return JSONResponse({"success": False, "error": "缺少必填字段", "missing_fields": errors}, status_code=400)

    order = models.Order(
        order_no=f"SO{datetime.datetime.utcnow():%Y%m%d%H%M%S}{uuid.uuid4().hex[:5].upper()}",
        shop_id=shop.id,
        customer_order_number=body.get("customer_order_number") or "",
        product_name=product_name,
        order_amount=float(order_amount),
        actual_received_amount=float(actual_received_amount),
        purchase_cost_rmb=float(purchase_cost_rmb),
        product_code=body.get("product_code") or "",
        declare_currency=body.get("declare_currency") or "USD",
        receiver_country=receiver.get("country", ""),
        receiver_name=receiver.get("name", ""),
        receiver_house_number=str(receiver.get("house_number", "")),
        receiver_state=receiver.get("state", ""),
        receiver_zip=receiver.get("zip", ""),
        receiver_address=receiver.get("address", ""),
        receiver_city=receiver.get("city", ""),
        receiver_phone=receiver.get("phone", ""),
        sender_name=sender.get("name", ""),
        sender_country=sender.get("country", ""),
        sender_state=sender.get("state", ""),
        sender_city=sender.get("city", ""),
        sender_address=sender.get("address", ""),
        sender_zip=sender.get("zip", ""),
        sender_phone=sender.get("phone", ""),
        package_count=int(package.get("count") or 1),
        total_weight=float(package.get("weight") or 0),
        created_by_name="外部API",
        created_at=datetime.datetime.utcnow(),
        source="api",
        review_status="pending",
    )
    order.set_declared_items([
        {
            "sku": it.get("sku", ""),
            "declared_name_en": it.get("name_en", ""),
            "declared_name_cn": it.get("name_cn", ""),
            "quantity": it.get("qty", ""),
            "declared_fob": it.get("fob", ""),
            "unit_weight": it.get("unit_weight", ""),
            "hs_code": it.get("hs_code", ""),
            "material": it.get("material", ""),
            "brand": it.get("brand", ""),
        }
        for it in items
    ])
    db.add(order)
    db.commit()
    db.refresh(order)

    return JSONResponse(
        {
            "success": True,
            "order_id": order.id,
            "order_no": order.order_no,
            "status": order.status,
            "review_status": order.review_status,
        },
        status_code=201,
    )
