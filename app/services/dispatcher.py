"""
物流商分发器：根据 LogisticsProvider.provider_type 选择对应的适配器模块。
后续新增物流商(例如顺丰/DHL等)时：
1. 在 services/ 下新增 xxx.py，实现 push_order(provider, order) 函数
2. 在下面 PROVIDER_MODULES 中注册 provider_type -> 模块
"""
from . import yunexpress

PROVIDER_MODULES = {
    "yunexpress": yunexpress,
}


def push_order(provider, order):
    module = PROVIDER_MODULES.get(provider.provider_type)
    if not module:
        return {
            "success": False,
            "tracking_number": "",
            "ye_order_no": "",
            "raw_response": "",
            "error": f"暂不支持的物流商类型: {provider.provider_type}",
        }
    return module.push_order(provider, order)
