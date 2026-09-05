# 跨境电商 ERP 系统（MVP）

基于 FastAPI + SQLite 构建的轻量级 ERP 系统，Docker 默认端口 **8311**。

## 已实现功能

1. **用户注册/审核**
   - 任何人可在 `/register` 注册账号，注册后状态为"待审核"，需管理员在 `/admin/users` 审核通过后才能登录使用。
   - **系统第一个注册的账号会自动成为管理员并直接激活**，用于初始化系统。
2. **店铺与权限**
   - 管理员在 `/admin/shops` 创建/管理店铺。
   - 管理员在 `/admin/users` 为每个用户分配所属店铺（可多选）。
   - 普通用户登录后，`/orders` 订单列表 **只能看到自己所属店铺的订单**；管理员可看到全部并可按店铺筛选。
3. **物流商 API 配置（可扩展多个物流商）**
   - `/admin/logistics`：新增/启用/停用/设默认/删除 物流商配置。
   - 每条配置包含：类型（当前实现云途 YunExpress，预留"其他"占位方便后续扩展）、名称、**客户代码 / 密钥 / APPID**（对应您截图中的三个字段）、API 地址、备注。
   - 后续接入更多物流商时，只需：
     1. 在 `app/services/` 下新增一个 `xxx.py`，实现 `push_order(provider, order)` 函数；
     2. 在 `app/services/dispatcher.py` 的 `PROVIDER_MODULES` 字典里注册 `provider_type -> 模块`；
     3. 在物流商配置新增页面的下拉框里加一个选项。
     其余系统代码（订单表单、推送按钮等）无需改动。
4. **发货订单（手动创建 + 推送云途）**
   - `/orders/new`：手动填写创建发货订单，字段参照您提供的 Excel 示例表格（客户订单号、产品代码=云途产品编码、附加服务、保价、签名服务、税号信息、收发件人信息、包裹信息、销售平台信息、支付信息、可多行的申报品名等）。
   - 额外新增的业务字段：**所属店铺、订单金额、实收金额、采购成本(人民币)**，以及**创建时间、创建人**（这两项由系统在保存时自动记录，无需手填）。
   - 订单详情页可选择一个已启用的物流商配置，点击"推送生成运单"调用云途接口创建发货订单，成功后回填运单号/云途订单号。

## 关于云途 OpenAPI 对接的说明

您提供的官方文档正文已经确认了完整的鉴权流程，系统已按此**真实实现**（不再是占位代码）：

1. **获取访问令牌**：`POST {base_url}/openapi/oauth2/token`，携带 `appId` / `appSecret` / `sourceKey` 换取 `accessToken`（有效期通常 7200 秒，当前实现是每次调用都重新获取一次，简单可靠；如未来订单量很大可以再优化为缓存令牌）。
2. **调用业务接口**：Headers 携带 `token`(accessToken)、`date`(毫秒时间戳)、`sign`。
3. **签名算法**：`sign = Base64( HMAC_SHA256( "body={请求体}&date={date}&method={method}&uri={uri}", secret=appSecret ) )`（无请求体时不含 `body=` 段）。
4. **创建订单接口**：`POST /v1/order/package/create`；正式环境 `https://openapi.yunexpress.cn`，沙箱环境 `https://openapi-sbx.yunexpress.cn`。请求体结构（`product_code`、`receiver`、`sender`、`packages`、`declaration_info`、`customs_number`、`extra_services`、`platform`、`payment` 等）已按文档字段实现，返回值 `{success, result:{waybill_number, tracking_number...}, msg, code}` 解析也已对接。

以上均已在 `app/services/yunexpress.py` 中实现，理论上可以直接联调。

**物流商配置表字段对应关系**（`/admin/logistics` 页面）：
- **APPID** → 云途 `appId`
- **密钥** → 云途 `appSecret`（既用于换取 accessToken，也用于计算签名）
- **sourceKey** → 云途"用户中心-用户信息"里的 sourceKey
- **客户代码** → 云途账号客户代码（部分场景/对账使用，当前下单接口暂未直接用到）
- **API地址** → 留空默认走正式环境，测试时可填沙箱地址 `https://openapi-sbx.yunexpress.cn`

**仍需要您协助确认/测试的点**：
- ✅ 附加服务代码表已按您提供的官方"附加服务表"实现：`20`偏远、`A0`单独报关、`G0`关税预付、`V1`代缴VAT、`10`出口退税、`VAS_IP`保价服务、`Ls0091`签名服务、`V4`云途预缴增值税号附加服务费。表单"附加服务"输入框可直接填写这些代码。
- 唯一不确定的是**保价服务(VAS_IP)金额的具体传值格式**：官方表格里 `extra_value` 给出的是 `EWFZ100001`(自定义保价保额)这个选项名，但没写清楚具体保价金额数字要怎么拼接进去。系统目前是猜测拼成 `"EWFZ100001:金额"`，建议先用沙箱环境实测一单确认格式是否正确。
- 建议先用**沙箱环境**跑通一单，把接口报错信息（订单详情页"查看接口返回原始数据"）发给我，方便对照错误码文档快速定位问题。


## 快速开始（Docker）

```bash
cd erp
docker compose up -d --build
```

访问 `http://服务器IP:8311`，用第一个注册的账号登录（自动成为管理员）。

也可以直接用 Docker 构建运行：
```bash
docker build -t cross-border-erp .
docker run -d -p 8311:8311 -v erp_data:/data --name cross-border-erp cross-border-erp
```

数据库为 SQLite，数据文件保存在容器内 `/data/erp.db`（已通过 volume 持久化，容器重建不丢数据）。

## 目录结构

```
erp/
  app/
    main.py               # FastAPI 入口
    models.py             # 数据库模型（用户/店铺/物流商配置/订单）
    database.py           # 数据库连接
    auth.py                # 登录鉴权
    routers/
      auth_router.py       # 登录/注册
      admin_router.py      # 用户审核、店铺管理、物流商配置
      orders_router.py     # 订单列表/创建/详情/推送
    services/
      yunexpress.py         # 云途适配器（占位实现，见上方说明）
      dispatcher.py         # 物流商分发器（后续多物流商扩展点）
    templates/              # 页面模板
    static/                 # 样式
  Dockerfile
  docker-compose.yml
  requirements.txt
```

## 后续可扩展方向（未实现，供参考）
- 云途"产品编码"字典的接口拉取与选择器（当前为手动填写产品代码）
- 订单批量导入 Excel（可直接复用您提供的示例表头）
- 物流轨迹查询、面单/标签下载与打印
- 订单利润报表（订单金额 - 实收金额 - 采购成本 - 物流成本）
