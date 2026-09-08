"""
发货后物流状态同步：抓取实际运费/重量(费用详情接口) + 抓取轨迹判断是否签收。
被两处调用：
1. 订单详情页"刷新物流状态"按钮 (routers/orders_router.py)
2. 后台定时任务 (main.py 里的 APScheduler job)
"""
import datetime
import json

from .. import models
from . import yunexpress


def refresh_order_tracking(db, order):
    """
    刷新单个订单的实际运费/重量/签收状态。
    需要 order.yunexpress_order_no(运单号) 已经存在(即已成功推送云途)。
    返回: dict(success, error)
    """
    waybill_number = order.yunexpress_order_no or order.tracking_number
    if not waybill_number:
        return {"success": False, "error": "该订单还没有云途运单号，无法查询"}

    provider = order.logistics_provider
    if not provider:
        provider = db.query(models.LogisticsProvider).filter(
            models.LogisticsProvider.is_default == True,  # noqa: E712
            models.LogisticsProvider.is_active == True,  # noqa: E712
        ).first()
    if not provider:
        return {"success": False, "error": "没有可用的物流商配置"}

    errors = []

    # 1. 运费/重量
    fee_result = yunexpress.get_order_fee_details(provider, waybill_number)
    if fee_result.get("success"):
        if fee_result.get("total_amount") is not None:
            order.actual_freight = fee_result.get("total_amount")
        if fee_result.get("currency"):
            order.freight_currency = fee_result.get("currency")
        if fee_result.get("actual_weight") is not None:
            order.actual_weight = fee_result.get("actual_weight")
        elif fee_result.get("charge_weight") is not None:
            order.actual_weight = fee_result.get("charge_weight")
        order.fee_details_json = json.dumps(fee_result.get("fee_details") or [], ensure_ascii=False)
    else:
        errors.append(f"运费查询: {fee_result.get('error') or '失败'}")

    # 2. 轨迹/签收状态
    track_result = yunexpress.get_tracking_full(provider, waybill_number)
    if track_result.get("success"):
        order.delivery_status = "delivered" if track_result.get("delivered") else "in_transit"
        order.last_track_event = track_result.get("latest_event_text") or ""
        order.tracking_raw = track_result.get("raw") or ""
    else:
        errors.append(f"轨迹查询: {track_result.get('error') or '失败'}")

    order.last_tracking_update_at = datetime.datetime.utcnow()
    db.commit()

    if errors and not fee_result.get("success") and not track_result.get("success"):
        return {"success": False, "error": "; ".join(errors)}
    return {"success": True, "error": "; ".join(errors) if errors else ""}


def refresh_all_pending_orders(db, limit: int = 100):
    """
    批量刷新所有"已成功推送但还未签收"的订单，供定时任务调用。
    返回: (成功数, 失败数)
    """
    orders = db.query(models.Order).filter(
        models.Order.status == "success",
        models.Order.delivery_status != "delivered",
        models.Order.yunexpress_order_no != "",
    ).limit(limit).all()

    ok, fail = 0, 0
    for order in orders:
        try:
            result = refresh_order_tracking(db, order)
            if result.get("success"):
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1
    return ok, fail
