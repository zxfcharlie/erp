"""
订单归档：/orders 主表只保留最近 N 条(默认200，环境变量 ORDER_ARCHIVE_KEEP 可调)，
超出的部分按创建时间从旧到新打包压缩存进 order_archives 表，并从 orders 表删除。

被两处调用：
1. 应用启动时跑一次(main.py)，处理存量数据
2. 后台定时任务(main.py 里的 APScheduler job)，定期清理新产生的超量数据
"""
import gzip
import json
import datetime

from .. import models

ORDER_COLUMNS = [c.name for c in models.Order.__table__.columns]


def _order_to_dict(order):
    d = {}
    for col in ORDER_COLUMNS:
        v = getattr(order, col)
        if isinstance(v, datetime.datetime):
            v = v.isoformat()
        d[col] = v
    return d


def archive_old_orders(db, keep: int = 200, batch_limit: int = 500):
    """
    把最旧的、超出 keep 条数的订单归档。batch_limit 是单次运行最多处理多少条，
    避免订单量特别大时一次性长事务卡住(定时任务下次再跑会继续处理剩下的)。
    返回归档的订单数。
    """
    total = db.query(models.Order).count()
    overflow = total - keep
    if overflow <= 0:
        return 0
    overflow = min(overflow, batch_limit)

    old_orders = db.query(models.Order).order_by(models.Order.created_at.asc()).limit(overflow).all()
    count = 0
    for o in old_orders:
        data = _order_to_dict(o)
        blob = gzip.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        archive = models.OrderArchive(
            order_no=o.order_no,
            shop_id=o.shop_id,
            customer_order_number=o.customer_order_number,
            tracking_number=o.tracking_number,
            yunexpress_order_no=o.yunexpress_order_no,
            product_code=o.product_code,
            status=o.status,
            delivery_status=o.delivery_status,
            order_amount=o.order_amount,
            actual_received_amount=o.actual_received_amount,
            purchase_cost_rmb=o.purchase_cost_rmb,
            actual_freight=o.actual_freight,
            created_by_name=o.created_by_name,
            created_at=o.created_at,
            data_gzip=blob,
        )
        db.add(archive)
        db.delete(o)
        count += 1
    db.commit()
    return count
