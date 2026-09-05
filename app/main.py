import os
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .database import Base, engine
from . import models  # noqa: F401  确保模型注册
from .routers import auth_router, admin_router, orders_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="跨境电商ERP系统")

SECRET_KEY = os.environ.get("SECRET_KEY", "please-change-this-secret-key")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=60 * 60 * 24 * 7)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(orders_router.router)


@app.get("/")
def root():
    return RedirectResponse("/orders", status_code=303)


@app.exception_handler(303)
async def redirect_handler(request: Request, exc):
    from fastapi.responses import RedirectResponse as RR
    return RR(exc.headers.get("Location", "/login"), status_code=303)
