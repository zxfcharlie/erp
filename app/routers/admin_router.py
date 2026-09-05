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
    shop = models.Shop(name=name, code=code, remark=remark)
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
