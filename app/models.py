import datetime
import json
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Float, Text, LargeBinary, ForeignKey, Table
)
from sqlalchemy.orm import relationship
from .database import Base

# 用户 <-> 店铺 多对多关联表
user_shop_association = Table(
    "user_shop",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("shop_id", Integer, ForeignKey("shops.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    real_name = Column(String(64), default="")
    role = Column(String(16), default="user")  # admin / user
    status = Column(String(16), default="pending")  # pending / approved / rejected
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    shops = relationship("Shop", secondary=user_shop_association, back_populates="users")

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def shop_ids(self):
        return [s.id for s in self.shops]


class Shop(Base):
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    code = Column(String(64), default="")
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    api_key = Column(String(64), default="", unique=False, index=True)  # 外部系统推送订单用的密钥

    # 默认发件人信息(预设)：新建订单选中该店铺后可自动填充发件人字段
    sender_name = Column(String(128), default="")
    sender_country = Column(String(8), default="")
    sender_state = Column(String(64), default="")
    sender_city = Column(String(64), default="")
    sender_address = Column(String(255), default="")
    sender_zip = Column(String(32), default="")
    sender_phone = Column(String(64), default="")

    users = relationship("User", secondary=user_shop_association, back_populates="shops")

    def sender_preset_dict(self):
        return {
            "sender_name": self.sender_name or "",
            "sender_country": self.sender_country or "",
            "sender_state": self.sender_state or "",
            "sender_city": self.sender_city or "",
            "sender_address": self.sender_address or "",
            "sender_zip": self.sender_zip or "",
            "sender_phone": self.sender_phone or "",
        }


class LogisticsProvider(Base):
    """物流商配置表 - 支持后续对接多个物流商"""
    __tablename__ = "logistics_providers"

    id = Column(Integer, primary_key=True, index=True)
    provider_type = Column(String(32), nullable=False, default="yunexpress")  # yunexpress / sf / ... 后续扩展
    name = Column(String(64), nullable=False)  # 显示名称，如"云途物流-主账号"
    customer_code = Column(String(64), default="")   # 客户代码
    api_key = Column(String(255), default="")        # 密钥(云途: 应用秘钥 appSecret，同时用于换取token和计算sign)
    app_id = Column(String(128), default="")         # APPID (云途: appId)
    source_key = Column(String(128), default="")      # 云途: sourceKey，见"用户中心-用户信息"
    base_url = Column(String(255), default="")       # API 基础地址
    extra_config = Column(Text, default="{}")         # 预留扩展字段(JSON字符串)
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    def get_extra(self):
        try:
            return json.loads(self.extra_config or "{}")
        except Exception:
            return {}


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(64), unique=True, index=True)  # 系统内部单号
    customer_order_number = Column(String(128), default="")  # 客户订单号
    product_name = Column(String(255), default="")  # 商品名称(外部系统传入，供人工审核时填写申报品名参考)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)

    # ---- 业务字段(新增) ----
    order_amount = Column(Float, default=0)          # 订单金额
    actual_received_amount = Column(Float, default=0)  # 实收金额
    purchase_cost_rmb = Column(Float, default=0)       # 采购成本(人民币)

    created_by_id = Column(Integer, ForeignKey("users.id"))
    created_by_name = Column(String(64), default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # ---- 物流商 / 状态 ----
    logistics_provider_id = Column(Integer, ForeignKey("logistics_providers.id"), nullable=True)
    status = Column(String(16), default="draft")  # draft / pushed / success / failed
    tracking_number = Column(String(128), default="")
    yunexpress_order_no = Column(String(128), default="")
    push_response = Column(Text, default="")

    # ---- 来源 / 审核 ----
    source = Column(String(16), default="web")            # web(手动创建) / api(外部系统推送)
    review_status = Column(String(16), default="approved")  # pending(待审核) / approved(已审核)
    reviewed_by_name = Column(String(64), default="")
    reviewed_at = Column(DateTime, nullable=True)
    push_error = Column(Text, default="")

    # ---- 实际物流费用/重量/签收状态(发货后从云途抓取) ----
    actual_weight = Column(Float, nullable=True)          # 实际/计费重量(kg)，来自"获取运单扣费详情"
    actual_freight = Column(Float, nullable=True)         # 实际物流运费合计(total_amount)
    freight_currency = Column(String(8), default="")      # 运费币种
    fee_details_json = Column(Text, default="")            # 扣费明细原始数据(JSON)
    delivery_status = Column(String(16), default="")       # "" / in_transit / delivered
    last_track_event = Column(String(255), default="")     # 最新一条轨迹描述，便于列表快速查看
    last_tracking_update_at = Column(DateTime, nullable=True)  # 最近一次抓取时间
    tracking_raw = Column(Text, default="")                 # 轨迹查询原始数据(JSON)

    # ---- 云途下单字段(对照示例表格) ----
    product_code = Column(String(64), default="")          # 产品代码(云途产品编码)
    additional_service = Column(String(128), default="")   # 附加服务
    insurance_service = Column(Boolean, default=False)      # 保价服务
    insurance_amount = Column(Float, default=0)             # 自定义保价保额
    signature_service = Column(Boolean, default=False)      # 签名服务
    vat_number = Column(String(64), default="")             # 增值税号
    eu_tax_number = Column(String(64), default="")          # 欧盟税号
    ioss_number = Column(String(64), default="")            # IOSS识别码
    production_sales_unit = Column(String(128), default="")  # 生产销售单位
    uscc = Column(String(64), default="")                    # 统一社会信用代码
    cod_flag = Column(String(16), default="")                # 代收代付
    cargo_type = Column(String(64), default="")              # 货物类型

    # 收件人
    receiver_country = Column(String(8), default="")
    receiver_name = Column(String(128), default="")
    receiver_id_number = Column(String(64), default="")
    receiver_company = Column(String(128), default="")
    receiver_address = Column(String(255), default="")
    receiver_city = Column(String(64), default="")
    receiver_state = Column(String(64), default="")
    receiver_zip = Column(String(32), default="")
    receiver_phone = Column(String(64), default="")
    receiver_house_number = Column(String(32), default="")
    receiver_email = Column(String(128), default="")
    receiver_short_address = Column(String(255), default="")

    # 包裹
    package_count = Column(Integer, default=1)
    total_weight = Column(Float, default=0)
    package_length = Column(Float, default=0)  # 长(cm)
    package_width = Column(Float, default=0)   # 宽(cm)
    package_height = Column(Float, default=0)  # 高(cm)

    # 发件人
    sender_name = Column(String(128), default="")
    sender_company = Column(String(128), default="")
    sender_address = Column(String(255), default="")
    sender_city = Column(String(64), default="")
    sender_state = Column(String(64), default="")
    sender_zip = Column(String(32), default="")
    sender_country = Column(String(8), default="")
    sender_phone = Column(String(64), default="")
    sender_email = Column(String(128), default="")
    sender_usci = Column(String(64), default="")

    # 销售平台信息
    platform_name = Column(String(128), default="")
    platform_address = Column(String(255), default="")
    platform_state = Column(String(64), default="")
    platform_zip = Column(String(32), default="")
    platform_phone = Column(String(64), default="")
    platform_email = Column(String(128), default="")
    platform_code = Column(String(64), default="")
    platform_sales_link = Column(String(255), default="")

    # 申报信息
    declare_currency = Column(String(8), default="USD")

    # 支付信息
    payment_platform = Column(String(64), default="")
    payment_account = Column(String(128), default="")
    payment_transaction_no = Column(String(128), default="")

    # 多条申报品名(json字符串存储列表)，对应表格中 SKU1/申报品名1... 可重复的多行
    declared_items_json = Column(Text, default="[]")

    shop = relationship("Shop")
    created_by = relationship("User")
    logistics_provider = relationship("LogisticsProvider")

    def get_declared_items(self):
        try:
            return json.loads(self.declared_items_json or "[]")
        except Exception:
            return []

    def set_declared_items(self, items):
        self.declared_items_json = json.dumps(items, ensure_ascii=False)


class ProductCode(Base):
    """
    云途产品编码库(本地缓存)。
    说明：目前云途"查询物流产品列表"接口的文档还没有提供给我，所以先做成
    管理员可在后台手动维护的一张编码表，供新建订单时做"产品代码"输入框的
    搜索自动填充。等拿到云途该接口的真实文档后，可以在这里加一个"从云途同步"
    的按钮，调用真实接口把数据拉过来，前端搜索逻辑完全不用改。
    """
    __tablename__ = "product_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(64), nullable=False, index=True)   # 云途产品编码
    name = Column(String(255), default="")                    # 产品名称/说明
    remark = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class DeclarationItemTemplate(Base):
    """
    常用申报品名模板：新建订单时填好一行申报品名后可"保存为常用"，
    以后新建订单时可以从下拉列表里直接选择自动填充这一行。
    """
    __tablename__ = "declaration_item_templates"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String(128), default="")           # 下拉列表展示名称(默认用英文品名)
    sku = Column(String(64), default="")
    declared_name_en = Column(String(255), default="")
    declared_name_cn = Column(String(255), default="")
    quantity = Column(Float, default=1)
    declared_fob = Column(Float, default=0)
    unit_weight = Column(Float, default=0)
    hs_code = Column(String(64), default="")
    material = Column(String(128), default="")
    brand = Column(String(128), default="")
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "sku": self.sku,
            "declared_name_en": self.declared_name_en,
            "declared_name_cn": self.declared_name_cn,
            "quantity": self.quantity,
            "declared_fob": self.declared_fob,
            "unit_weight": self.unit_weight,
            "hs_code": self.hs_code,
            "material": self.material,
            "brand": self.brand,
        }


class OrderArchive(Base):
    """
    历史订单归档表。
    /orders 主列表只保留最近 N 条(默认200，见 ORDER_ARCHIVE_KEEP 环境变量)，
    超出的老订单会被定时任务打包成 gzip 压缩的 JSON 存到这里，同时从 orders 表删除，
    减小主表体积、提升日常查询/列表性能。
    这里只保留几个常用来搜索/展示的轻量字段做索引；订单完整的~50个字段都在 data_gzip
    里，查看详情时才解压，不影响列表页的查询速度。
    """
    __tablename__ = "order_archives"

    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(64), index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), index=True)
    customer_order_number = Column(String(128), default="", index=True)
    tracking_number = Column(String(128), default="", index=True)
    yunexpress_order_no = Column(String(128), default="")
    product_code = Column(String(64), default="")
    status = Column(String(16), default="")
    delivery_status = Column(String(16), default="")
    order_amount = Column(Float, default=0)
    actual_received_amount = Column(Float, default=0)
    purchase_cost_rmb = Column(Float, default=0)
    actual_freight = Column(Float, nullable=True)
    created_by_name = Column(String(64), default="")
    created_at = Column(DateTime, index=True)
    archived_at = Column(DateTime, default=datetime.datetime.utcnow)
    data_gzip = Column(LargeBinary)  # 压缩后的完整订单字段(JSON)

    shop = relationship("Shop")

    def to_full_dict(self):
        import gzip
        if not self.data_gzip:
            return {}
        raw = gzip.decompress(self.data_gzip)
        return json.loads(raw.decode("utf-8"))
