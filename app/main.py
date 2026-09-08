import os
import secrets
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.gzip import GZipMiddleware

from .database import Base, engine, auto_migrate, SessionLocal
from . import models
from .routers import auth_router, admin_router, orders_router, api_router, reports_router, archive_router

Base.metadata.create_all(bind=engine)
auto_migrate()


def _backfill_shop_api_keys():
    """给老数据里 api_key 还是空的店铺自动生成一个，保证外部推送接口能用"""
    db = SessionLocal()
    try:
        shops = db.query(models.Shop).filter(
            (models.Shop.api_key == None) | (models.Shop.api_key == "")  # noqa: E711
        ).all()
        for s in shops:
            s.api_key = secrets.token_hex(20)
        if shops:
            db.commit()
    finally:
        db.close()


def _archive_old_orders_once():
    """启动时先跑一次归档，处理存量超量数据(比如刚上线这个功能时表里已经有很多订单)"""
    from .services.archive import archive_old_orders
    keep = int(os.environ.get("ORDER_ARCHIVE_KEEP", "200"))
    db = SessionLocal()
    try:
        count = archive_old_orders(db, keep=keep)
        if count:
            print(f"[startup] 启动时归档了 {count} 条老订单(保留最近 {keep} 条)")
    finally:
        db.close()


_backfill_shop_api_keys()
_archive_old_orders_once()

app = FastAPI(title="跨境电商ERP系统")

# 小内存服务器优化：网页响应(尤其是订单列表/详情这类较大的HTML)开启gzip压缩，
# 降低带宽占用；CPU开销很小，8GB内存/普通CPU的机器完全无感。
app.add_middleware(GZipMiddleware, minimum_size=500)

SECRET_KEY = os.environ.get("SECRET_KEY", "please-change-this-secret-key")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=60 * 60 * 24 * 7)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(orders_router.router)
app.include_router(api_router.router)
app.include_router(reports_router.router)
app.include_router(archive_router.router)


@app.get("/")
def root():
    return RedirectResponse("/orders", status_code=303)


@app.exception_handler(303)
async def redirect_handler(request: Request, exc):
    from fastapi.responses import RedirectResponse as RR
    return RR(exc.headers.get("Location", "/login"), status_code=303)


# ---------------- 后台定时任务 ----------------
# 小内存服务器优化：显式用单线程执行器 + max_instances=1 + coalesce=True，
# 避免任务偶尔跑得比间隔久时被同时并发触发多份，占用额外内存/连接。
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.executors.pool import ThreadPoolExecutor as APSThreadPoolExecutor

    def _scheduled_refresh_job():
        """定期抓取已推送订单的实际运费/签收状态"""
        from .services.sync import refresh_all_pending_orders
        db = SessionLocal()
        try:
            ok, fail = refresh_all_pending_orders(db)
            if ok or fail:
                print(f"[scheduler] 定时刷新物流状态完成: 成功{ok}单 失败{fail}单")
        finally:
            db.close()

    def _scheduled_archive_job():
        """定期把超出保留数量的老订单归档压缩，控制主表体积"""
        from .services.archive import archive_old_orders
        keep = int(os.environ.get("ORDER_ARCHIVE_KEEP", "200"))
        db = SessionLocal()
        try:
            count = archive_old_orders(db, keep=keep)
            if count:
                print(f"[scheduler] 定时归档完成: 归档了 {count} 条老订单(保留最近 {keep} 条)")
        finally:
            db.close()

    _scheduler = BackgroundScheduler(
        executors={"default": APSThreadPoolExecutor(1)},  # 单线程执行器，控制内存/并发
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
    )
    # 轨迹/运费同步：默认每60分钟一次，环境变量 TRACKING_SYNC_MINUTES 可调
    _tracking_interval = int(os.environ.get("TRACKING_SYNC_MINUTES", "60"))
    _scheduler.add_job(_scheduled_refresh_job, "interval", minutes=_tracking_interval, id="tracking_sync")
    # 订单归档：默认每24小时一次，环境变量 ORDER_ARCHIVE_CHECK_HOURS 可调
    _archive_interval = int(os.environ.get("ORDER_ARCHIVE_CHECK_HOURS", "24"))
    _scheduler.add_job(_scheduled_archive_job, "interval", hours=_archive_interval, id="order_archive")
    _scheduler.start()
except Exception as e:
    print(f"[scheduler] 定时任务启动失败(不影响其余功能): {e}")
