from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import List, Optional
from .. import models
from ..database import get_db
from ..auth import require_admin, hash_password

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")


# ---------------- 用户管理 ----------------
@router.get("/users", response_class=HTMLResponse)
def user_list(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    users = db.query(models.User).order_by(models.User.created_at.desc()).all()
    shops = db.query(models.Shop).all()
    return templates.TemplateResponse(
        "admin_users.html",
        {"request": request, "user": admin, "users": users, "shops": shops},
    )


@router.post("/users/{user_id}/approve")
def approve_user(user_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    u = db.query(models.User).get(user_id)
    if u:
        u.status = "approved"
        db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/reject")
def reject_user(user_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    u = db.query(models.User).get(user_id)
    if u:
        u.status = "rejected"
        db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/role")
def set_role(user_id: int, role: str = Form(...), db: Session = Depends(get_db), admin=Depends(require_admin)):
    u = db.query(models.User).get(user_id)
    if u and role in ("admin", "user"):
        u.role = role
        db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/shops")
def set_user_shops(
    user_id: int,
    shop_ids: Optional[List[int]] = Form(None),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    u = db.query(models.User).get(user_id)
    if u:
        shop_ids = shop_ids or []
        u.shops = db.query(models.Shop).filter(models.Shop.id.in_(shop_ids)).all()
        db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/reset_password")
def reset_password(user_id: int, new_password: str = Form(...), db: Session = Depends(get_db), admin=Depends(require_admin)):
    u = db.query(models.User).get(user_id)
    if u and len(new_password) >= 6:
        u.password_hash = hash_password(new_password)
        db.commit()
    return RedirectResponse("/admin/users", status_code=303)


# ---------------- 店铺管理 ----------------
@router.get("/shops", response_class=HTMLResponse)
def shop_list(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    shops = db.query(models.Shop).order_by(models.Shop.created_at.desc()).all()
    return templates.TemplateResponse(
        "admin_shops.html", {"request": request, "user": admin, "shops": shops}
    )


@router.post("/shops/create")
def shop_create(
    name: str = Form(...),
    code: str = Form(""),
    remark: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    import secrets
    shop = models.Shop(name=name, code=code, remark=remark, api_key=secrets.token_hex(20))
    db.add(shop)
    db.commit()
    return RedirectResponse("/admin/shops", status_code=303)


@router.post("/shops/{shop_id}/delete")
def shop_delete(shop_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    shop = db.query(models.Shop).get(shop_id)
    if shop:
        db.delete(shop)
        db.commit()
    return RedirectResponse("/admin/shops", status_code=303)


@router.post("/shops/{shop_id}/regenerate-key")
def shop_regenerate_key(shop_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    import secrets
    shop = db.query(models.Shop).get(shop_id)
    if shop:
        shop.api_key = secrets.token_hex(20)
        db.commit()
    return RedirectResponse("/admin/shops", status_code=303)


# ---------------- 物流商配置 ----------------
@router.get("/logistics", response_class=HTMLResponse)
def logistics_list(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    providers = db.query(models.LogisticsProvider).order_by(models.LogisticsProvider.created_at.desc()).all()
    return templates.TemplateResponse(
        "admin_logistics.html", {"request": request, "user": admin, "providers": providers}
    )


@router.post("/logistics/create")
def logistics_create(
    provider_type: str = Form("yunexpress"),
    name: str = Form(...),
    customer_code: str = Form(""),
    api_key: str = Form(""),
    app_id: str = Form(""),
    source_key: str = Form(""),
    base_url: str = Form(""),
    remark: str = Form(""),
    is_default: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    if is_default:
        db.query(models.LogisticsProvider).update({models.LogisticsProvider.is_default: False})
    provider = models.LogisticsProvider(
        provider_type=provider_type,
        name=name,
        customer_code=customer_code,
        api_key=api_key,
        app_id=app_id,
        source_key=source_key,
        base_url=base_url,
        remark=remark,
        is_default=bool(is_default),
    )
    db.add(provider)
    db.commit()
    return RedirectResponse("/admin/logistics", status_code=303)


@router.post("/logistics/{provider_id}/toggle")
def logistics_toggle(provider_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    p = db.query(models.LogisticsProvider).get(provider_id)
    if p:
        p.is_active = not p.is_active
        db.commit()
    return RedirectResponse("/admin/logistics", status_code=303)


@router.post("/logistics/{provider_id}/set_default")
def logistics_set_default(provider_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    db.query(models.LogisticsProvider).update({models.LogisticsProvider.is_default: False})
    p = db.query(models.LogisticsProvider).get(provider_id)
    if p:
        p.is_default = True
        db.commit()
    return RedirectResponse("/admin/logistics", status_code=303)


@router.post("/logistics/{provider_id}/delete")
def logistics_delete(provider_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    p = db.query(models.LogisticsProvider).get(provider_id)
    if p:
        db.delete(p)
        db.commit()
    return RedirectResponse("/admin/logistics", status_code=303)


# ---------------- 产品编码库(云途产品代码，暂为本地手动维护) ----------------
@router.get("/products", response_class=HTMLResponse)
def product_list(request: Request, db: Session = Depends(get_db), admin=Depends(require_admin)):
    products = db.query(models.ProductCode).order_by(models.ProductCode.created_at.desc()).all()
    yunexpress_providers = db.query(models.LogisticsProvider).filter(
        models.LogisticsProvider.provider_type == "yunexpress",
        models.LogisticsProvider.is_active == True,  # noqa: E712
    ).all()
    return templates.TemplateResponse(
        "admin_products.html",
        {
            "request": request, "user": admin, "products": products,
            "yunexpress_providers": yunexpress_providers,
            "sync_error": request.query_params.get("sync_error"),
            "sync_count": request.query_params.get("sync_count"),
        },
    )


@router.post("/products/create")
def product_create(
    code: str = Form(...),
    name: str = Form(""),
    remark: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    p = models.ProductCode(code=code.strip(), name=name.strip(), remark=remark.strip())
    db.add(p)
    db.commit()
    return RedirectResponse("/admin/products", status_code=303)


@router.post("/products/import")
def product_import(
    bulk_text: str = Form(""),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    """
    批量导入：每行一个产品，格式 编码,名称,备注(名称/备注可省略)
    方便把云途后台产品列表页面复制过来的文本快速批量录入。
    """
    count = 0
    for line in bulk_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        code = parts[0]
        if not code:
            continue
        name = parts[1] if len(parts) > 1 else ""
        remark = parts[2] if len(parts) > 2 else ""
        db.add(models.ProductCode(code=code, name=name, remark=remark))
        count += 1
    db.commit()
    return RedirectResponse("/admin/products", status_code=303)


@router.post("/products/{product_id}/delete")
def product_delete(product_id: int, db: Session = Depends(get_db), admin=Depends(require_admin)):
    p = db.query(models.ProductCode).get(product_id)
    if p:
        db.delete(p)
        db.commit()
    return RedirectResponse("/admin/products", status_code=303)


@router.post("/products/sync_yunexpress")
def product_sync_yunexpress(provider_id: int = Form(...), db: Session = Depends(get_db), admin=Depends(require_admin)):
    """调用云途 查询物流产品列表 接口，把结果 upsert 进本地产品编码库"""
    provider = db.query(models.LogisticsProvider).get(provider_id)
    if not provider:
        return RedirectResponse("/admin/products?sync_error=" + "未找到该物流商配置", status_code=303)

    from ..services.yunexpress import get_product_list  # 延迟导入，避免循环依赖

    result = get_product_list(provider)
    if not result.get("success"):
        return RedirectResponse(f"/admin/products?sync_error={result.get('error') or '同步失败'}", status_code=303)

    existing = {p.code: p for p in db.query(models.ProductCode).all()}
    count = 0
    for item in result["products"]:
        code = (item.get("code") or "").strip()
        if not code:
            continue
        if code in existing:
            existing[code].name = item.get("name", "")
            existing[code].remark = "来自云途同步"
        else:
            db.add(models.ProductCode(code=code, name=item.get("name", ""), remark="来自云途同步"))
        count += 1
    db.commit()
    return RedirectResponse(f"/admin/products?sync_count={count}", status_code=303)


@router.post("/archive-now")
def archive_now(db: Session = Depends(get_db), admin=Depends(require_admin)):
    """管理员手动立即触发一次订单归档，不用等定时任务(默认24小时一次)"""
    import os
    from ..services.archive import archive_old_orders
    keep = int(os.environ.get("ORDER_ARCHIVE_KEEP", "200"))
    count = archive_old_orders(db, keep=keep)
    return RedirectResponse(f"/orders?archived={count}", status_code=303)
