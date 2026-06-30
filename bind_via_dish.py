#!/usr/bin/env python3
import os
import sys
import json
import requests
from pathlib import Path

WORKSPACE_DIR = Path("/home/akbarhann/project/task-weekly")
AUTOMATION_DIR = WORKSPACE_DIR / "src" / "shopee-omzet-automation"
sys.path.insert(0, str(AUTOMATION_DIR))

SELLER_BASE = "https://foody.shopee.co.id"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"

def build_headers(tob_token, entity_id, extra_cookies):
    cookies = extra_cookies.copy()
    cookies["shopee_tob_token"] = tob_token
    cookies["shopee_tob_entity_id"] = entity_id
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return {
        "Host": "foody.shopee.co.id",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Cookie": cookie_str,
        "X-Sf-Platform": "2",
        "Operate-Source": "partnerapp",
        "Origin": "https://partner.shopee.co.id",
        "Referer": "https://partner.shopee.co.id/",
    }

def run():
    session_file = WORKSPACE_DIR / "weekly" / "data" / "session.json"
    if not session_file.exists():
        print(f"[-] Session file {session_file} does not exist!")
        return

    session_data = json.loads(session_file.read_text())
    tob_token = session_data.get("shopee_tob_token")
    entity_id = "21941677" # Test Store ID
    extra_cookies = session_data.get("extra_cookies", {})

    headers = build_headers(tob_token, entity_id, extra_cookies)
    
    group_id = "3151215842979328" # Topping Dummy Antigravity Edited
    dish_id = "3143029405545472" # [TEST] Menu Coba
    
    url = f"{SELLER_BASE}/api/seller/store/dishes/{dish_id}"
    
    # Let's test multiple structures inside the dish object
    base_dish = {
        "id": dish_id,
        "name": "[TEST] Menu Coba",
        "price": "100000000",
        "catalog_id": "3142001330862080",
        "description": "Desc Coba",
        "listing_status": 1,
        "available": True,
        "sale_week_bit": 127,
        "sale_start_time": 0,
        "sale_end_time": 86399,
        "time_for_sales": [
            {
                "sale_start_time": 0,
                "sale_end_time": 86399
            }
        ]
    }

    payloads = [
        # Option 1: option_group_ids list inside dish
        {
            "dish": {**base_dish, "option_group_ids": [group_id]}
        },
        # Option 2: option_groups list inside dish
        {
            "dish": {**base_dish, "option_groups": [{"id": group_id}]}
        },
        # Option 3: option_group_ids list at the root level
        {
            "dish": base_dish,
            "option_group_ids": [group_id]
        }
    ]

    for idx, payload in enumerate(payloads):
        print(f"\n--- Testing payload option {idx+1} ---")
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            print(f"[+] HTTP Status: {resp.status_code}")
            print(f"[+] Response JSON:\n{json.dumps(resp.json(), indent=2)}")
        except Exception as e:
            print(f"[-] Request failed: {e}")

if __name__ == "__main__":
    run()
