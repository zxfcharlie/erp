import datetime
import json
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Float, Text, ForeignKey, Table
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

    users = relationship("User", secondary=user_shop_association, back_populates="shops")


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
    push_error = Column(Text, default="")

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
