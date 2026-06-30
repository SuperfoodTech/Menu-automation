# -*- coding: utf-8 -*-
from shopee.core.adapter import ShopeeAdapter
from grab.core.adapter import GrabAdapter

def get_adapter(platform: str):
    """Factory function untuk mendapatkan adapter berdasarkan platform."""
    adapters = {
        "shopee": ShopeeAdapter,
        "grab": GrabAdapter,
    }
    cls = adapters.get(platform)
    if not cls:
        raise ValueError(f"Platform tidak didukung: {platform}")
    return cls()
