"""
云途物流(YunExpress) OpenAPI 对接适配器
======================================
已根据您提供的云途官方"授权介绍"+"签名算法"文档，实现了**完整的真实鉴权流程**：

1. 获取访问令牌 accessToken (OAuth2 client_credentials 模式)
   POST {base_url}/openapi/oauth2/token
   Body: {"grantType": "client_credentials", "appId": ..., "appSecret": ..., "sourceKey": ...}
   Response: {"expiresIn": 7200, "accessToken": "..."}

2. 调用业务接口(如创建订单)时，Headers 携带：
   token: <accessToken>
   date:  <当前毫秒时间戳>
   sign:  <签名结果>

3. 签名算法(HMAC-SHA256 + Base64)：
   content = "body={requestBody}&date={date}&method={method}&uri={uri}"
             （字段名正序拼接；如无请求体则不含 body= 段）
   sign = Base64( HMAC_SHA256( content, secret=appSecret ) )

以上鉴权与签名部分现在均为真实实现。

创建订单接口本身(product_code / receiver / sender / packages / declaration_info 等
请求体结构，以及返回值结构)按您此前提供的"订单创建"文档正文实现，见 build_payload() /
parse_response()。

【物流商配置表字段对应关系】(见 models.LogisticsProvider / 后台"物流商配置"页面)：
    app_id       -> 云途 appId
    api_key      -> 云途 appSecret（既用于换取 accessToken，也用于计算 sign）
    source_key   -> 云途 sourceKey（用户中心-用户信息 里查看）
    customer_code-> 云途客户代码（部分场景/对账使用，本接口暂未直接用到）
    base_url     -> 留空使用正式环境；沙箱测试可填 https://openapi-sbx.yunexpress.cn

如果实际联调时仍报错（例如 accessToken 获取失败、签名校验不通过），把云途返回的
原始错误信息（订单详情页"查看接口返回原始数据"里能看到）发给我，我再针对性调整。

【附加服务代码表】(extra_code) 已按官方"附加服务表"实现：
    20      偏远(接受偏远附加费)
    A0      单独报关(extra_value 填报送文件地址)
    G0      关税预付
    V1      代缴VAT(云途IOSS代缴服务)
    10      出口退税
    VAS_IP  保价服务(本系统"自定义保价保额"对应其中 EWFZ100001 选项，
            具体金额拼接格式官方未写明，建议沙箱环境先测试确认)
    Ls0091  签名服务
    V4      云途预缴增值税号附加服务费
表单里的"附加服务"输入框可直接填写以上任意 extra_code，实现对应服务。
"""
import base64
import hmac
import hashlib
import json
import time
import requests

BASE_URL_PROD = "https://openapi.yunexpress.cn"
BASE_URL_SANDBOX = "https://openapi-sbx.yunexpress.cn"
TOKEN_PATH = "/openapi/oauth2/token"
CREATE_ORDER_PATH = "/v1/order/package/create"
CANCEL_ORDER_PATH = "/v1/order/cancel"


class YunExpressError(Exception):
    pass


def get_access_token(provider):
    """
    通过 OAuth2 client_credentials 模式换取 accessToken。
    注意：为简化实现，本函数每次调用都重新获取一次新令牌(未做本地缓存)，
    accessToken 有效期 expiresIn 通常为 7200 秒，如未来订单量很大需要减少请求次数，
    可以把 accessToken 和过期时间缓存到 LogisticsProvider.extra_config 里。
    """
    base_url = provider.base_url or BASE_URL_PROD
    body = {
        "grantType": "client_credentials",
        "appId": provider.app_id or "",
        "appSecret": provider.api_key or "",
        "sourceKey": provider.source_key or "",
    }
    resp = requests.post(
        f"{base_url}{TOKEN_PATH}",
        headers={"Content-Type": "application/json;charset=utf-8"},
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    access_token = data.get("accessToken")
    if not access_token:
        raise YunExpressError(f"获取云途访问令牌失败: {json.dumps(data, ensure_ascii=False)}")
    return access_token


def build_sign(date_ms: str, method: str, uri: str, body_str: str, secret: str) -> str:
    """
    HMAC-SHA256 + Base64 签名，字段按 body/date/method/uri 正序拼接。
    没有请求体时不包含 body= 段。
    """
    if body_str:
        content = f"body={body_str}&date={date_ms}&method={method}&uri={uri}"
    else:
        content = f"date={date_ms}&method={method}&uri={uri}"
    digest = hmac.new(secret.encode("utf-8"), content.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _split_name(full_name: str):
    """云途要求 first_name / last_name 分开，这里按空格粗略切分，切不出来则整体放 last_name"""
    full_name = (full_name or "").strip()
    if not full_name:
        return "", ""
    parts = full_name.split(" ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", full_name


def build_payload(order) -> dict:
    """将系统内 Order 对象转换为云途"创建订单"接口所需的真实请求体结构"""
    declared_items = order.get_declared_items()

    receiver_first, receiver_last = _split_name(order.receiver_name)
    sender_first, sender_last = _split_name(order.sender_name)

    declaration_info = []
    for it in declared_items:
        declaration_info.append({
            "sku_code": it.get("sku", ""),
            "name_local": it.get("declared_name_cn", ""),
            "name_en": it.get("declared_name_en", ""),
            "quantity": int(float(it.get("quantity") or 0)),
            "unit_price": float(it.get("declared_fob") or 0),
            "unit_weight": float(it.get("unit_weight") or 0),
            "hs_code": it.get("hs_code", ""),
            "sales_url": order.platform_sales_link or "",
            "currency": order.declare_currency or "USD",
            "material": it.get("material", ""),
            "purpose": "",
            "brand": it.get("brand", ""),
            "spec": "",
            "model": "",
            "remark": "",
        })

    extra_services = []
    if order.insurance_service:
        # 保价服务对应云途 extra_code = VAS_IP，按官方"附加服务表"该服务的
        # extra_value 需在 1:BJFA(固定金额) / 2:BJFR(运费费率) / 3:BJDR(申报价值费率) /
        # 4:BJFDR(运费+申报价值*费率) / 5:EWFZ100001(自定义保价保额) 中选择。
        # 本系统对应"自定义保价保额"字段，采用第5种；
        # TODO: 具体保价金额应如何拼接进 extra_value(例如是否为 "EWFZ100001:金额" 格式)
        # 官方表格未写明，建议先用沙箱环境实测确认格式后再上线。
        extra_services.append({
            "extra_code": "VAS_IP",
            "extra_value": f"EWFZ100001:{order.insurance_amount}" if order.insurance_amount else "EWFZ100001",
        })
    if order.signature_service:
        # 签名服务，官方代码 Ls0091，extra_value 为空
        extra_services.append({"extra_code": "Ls0091", "extra_value": ""})
    if order.additional_service:
        # 自由填写的附加服务代码，可直接填写云途"附加服务表"中的 extra_code，
        # 例如：20(偏远) / A0(单独报关，extra_value填报送文件地址) / G0(关税预付) /
        # V1(代缴VAT) / 10(出口退税) / V4(云途预缴增值税号附加服务费)
        extra_services.append({"extra_code": order.additional_service, "extra_value": ""})

    payload = {
        "product_code": order.product_code,
        "customer_order_number": order.customer_order_number or "",
        "order_numbers": {
            "waybill_number": "",
            "platform_order_number": "",
            "tracking_number": "",
            "reference_numbers": [],
        },
        "weight_unit": "KG",
        "size_unit": "CM",
        "dangerous_goods_type": "",
        "packages": [
            {
                "length": order.package_length or 0,
                "width": order.package_width or 0,
                "height": order.package_height or 0,
                "weight": order.total_weight or 0,
            }
        ],
        "receiver": {
            "first_name": receiver_first,
            "last_name": receiver_last,
            "company": order.receiver_company or "",
            "country_code": order.receiver_country or "",
            "province": order.receiver_state or "",
            "city": order.receiver_city or "",
            "address_lines": [order.receiver_address or ""],
            "postal_code": order.receiver_zip or "",
            "phone_number": order.receiver_phone or "",
            "email": order.receiver_email or "",
            "certificate_type": "",
            "certificate_code": order.receiver_id_number or "",
        },
        "declaration_info": declaration_info,
        "sender": {
            "first_name": sender_first,
            "last_name": sender_last,
            "company": order.sender_company or "",
            "country_code": order.sender_country or "",
            "province": order.sender_state or "",
            "city": order.sender_city or "",
            "address_lines": [order.sender_address or ""],
            "postal_code": order.sender_zip or "",
            "phone_number": order.sender_phone or "",
            "email": order.sender_email or "",
            "certificate_type": "",
            "certificate_code": "",
        },
        "customs_number": {
            "tax_number": "",
            "ioss_code": order.ioss_number or "",
            "vat_code": order.vat_number or "",
            "eori_number": order.eu_tax_number or "",
        },
        "extra_services": extra_services,
        "platform_account_code": "",
        "source_code": "",
        "sensitive_type": "W",
        "label_type": "PDF",
        "manufacture_sales_name": order.production_sales_unit or "",
        "credit_code": order.uscc or "",
    }
    if order.platform_name:
        payload["platform"] = {
            "name": order.platform_name,
            "address": order.platform_address,
            "state": order.platform_state,
            "zip": order.platform_zip,
            "phone": order.platform_phone,
            "email": order.platform_email,
            "code": order.platform_code,
        }
    if order.payment_platform:
        payload["payment"] = {
            "platform": order.payment_platform,
            "account": order.payment_account,
            "transaction_no": order.payment_transaction_no,
        }
    return payload


def parse_response(resp_json: dict):
    """
    按云途官方返回结构解析：
    {"t":..., "success": true/false, "result": {...}, "msg": "...", "code": "..."}
    result 成功时包含: customer_order_number, track_type, waybill_number, tracking_number, ...
    """
    success = bool(resp_json.get("success"))
    result = resp_json.get("result") or {}
    tracking_number = result.get("tracking_number") or ""
    waybill_number = result.get("waybill_number") or ""
    return success, tracking_number, waybill_number


def _call_signed_api(provider, method: str, path: str, payload: dict):
    """统一封装：获取 accessToken -> 计算签名 -> 发起请求"""
    base_url = provider.base_url or BASE_URL_PROD
    access_token = get_access_token(provider)

    date_ms = str(int(time.time() * 1000))
    body_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload else ""
    sign = build_sign(date_ms, method, path, body_str, provider.api_key or "")

    headers = {
        "Content-Type": "application/json;charset=utf-8",
        "token": access_token,
        "date": date_ms,
        "sign": sign,
        "Accept-Language": "zh-CN",
    }
    resp = requests.request(
        method,
        f"{base_url}{path}",
        headers=headers,
        data=body_str.encode("utf-8") if body_str else None,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def push_order(provider, order):
    """
    调用云途 /v1/order/package/create 接口创建发货订单。
    provider: models.LogisticsProvider
    order: models.Order
    返回: dict(success, tracking_number, ye_order_no, raw_response, error)
    """
    try:
        payload = build_payload(order)
        resp_json = _call_signed_api(provider, "POST", CREATE_ORDER_PATH, payload)
        success, tracking_number, waybill_number = parse_response(resp_json)
        return {
            "success": success,
            "tracking_number": tracking_number,
            "ye_order_no": waybill_number,
            "raw_response": json.dumps(resp_json, ensure_ascii=False),
            "error": "" if success else f"{resp_json.get('code', '')} {resp_json.get('msg', '')}".strip(),
        }
    except Exception as e:
        return {
            "success": False,
            "tracking_number": "",
            "ye_order_no": "",
            "raw_response": "",
            "error": f"调用云途接口失败: {e}",
        }


def cancel_order(provider, waybill_number: str):
    """撤销运单(仅支持已预报或草稿状态) POST /v1/order/cancel"""
    try:
        resp_json = _call_signed_api(provider, "POST", CANCEL_ORDER_PATH, {"waybill_number": waybill_number})
        return {"success": bool(resp_json.get("success")), "raw_response": json.dumps(resp_json, ensure_ascii=False)}
    except Exception as e:
        return {"success": False, "raw_response": "", "error": f"撤销运单失败: {e}"}
