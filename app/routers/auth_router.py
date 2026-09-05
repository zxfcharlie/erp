from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from .. import models
from ..database import get_db
from ..auth import hash_password, verify_password, get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "error": None})


@router.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    real_name: str = Form(""),
    db: Session = Depends(get_db),
):
    error = None
    if password != password2:
        error = "两次输入的密码不一致"
    elif len(password) < 6:
        error = "密码长度至少6位"
    elif db.query(models.User).filter(models.User.username == username).first():
        error = "用户名已存在"
    if error:
        return templates.TemplateResponse("register.html", {"request": request, "error": error})

    is_first_user = db.query(models.User).count() == 0
    user = models.User(
        username=username,
        password_hash=hash_password(password),
        real_name=real_name,
        role="admin" if is_first_user else "user",
        status="approved" if is_first_user else "pending",
    )
    db.add(user)
    db.commit()
    return templates.TemplateResponse(
        "register.html",
        {
            "request": request,
            "error": None,
            "success": "注册成功，第一个注册用户自动成为管理员并已激活，可直接登录；"
            if is_first_user
            else "注册成功，请等待管理员审核通过后登录。",
        },
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "用户名或密码错误"}
        )
    request.session["user_id"] = user.id
    if user.status != "approved":
        return RedirectResponse("/pending", status_code=303)
    return RedirectResponse("/orders", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/pending", response_class=HTMLResponse)
def pending_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.status == "approved":
        return RedirectResponse("/orders", status_code=303)
    return templates.TemplateResponse("pending.html", {"request": request, "user": user})
