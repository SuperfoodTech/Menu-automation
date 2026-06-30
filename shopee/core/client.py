# -*- coding: utf-8 -*-
import json
import requests
import hashlib
import time
import uuid
from pathlib import Path
from selenium.webdriver.chrome.options import Options

WORKSPACE_DIR = Path(__file__).resolve().parents[3]
SELLER_BASE = "https://foody.shopee.co.id"
MMS_PREUPLOAD = "https://api.mms.shopee.co.id/uploadapi/api/v1/image/preupload"
WS_UPLOAD     = "https://up-ws-id.img.susercontent.com/file/upload"
IMG_PLAY_BASE = "https://down-id.img.susercontent.com/file"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"

# Patch user-data-dir to portal_f profile
orig_add_argument = Options.add_argument
def _custom_add_argument(self, argument):
    if "--user-data-dir=" in argument:
        target_dir = WORKSPACE_DIR / 'menu' / 'shopee' / 'core' / 'portal_f'
        argument = f"--user-data-dir={target_dir}"
        for lock_name in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
            lock_file = target_dir / lock_name
            if lock_file.exists() or lock_file.is_symlink():
                try:
                    lock_file.unlink(missing_ok=True)
                except:
                    pass
    elif "--profile-directory=" in argument:
        argument = "--profile-directory=profile_portal_f"
    orig_add_argument(self, argument)

if not hasattr(Options, "_patched_modify"):
    Options.add_argument = _custom_add_argument
    Options._patched_modify = True

class ShopeeClient:
    def __init__(self, tob_token: str, entity_id: str, extra_cookies: dict = None):
        self.tob_token     = tob_token
        self.extra_cookies = extra_cookies or {}
        self.entity_id     = entity_id or self.extra_cookies.get("shopee_foody_mid", "")
        self.session       = requests.Session()
        self.user_agent    = USER_AGENT

    def _seller_headers(self, override_entity_id: str = None) -> dict:
        eid = override_entity_id or self.entity_id
        cookies = self.extra_cookies.copy()
        cookies["shopee_tob_token"]     = self.tob_token
        cookies["shopee_tob_entity_id"] = eid
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())

        return {
            "Host":           "foody.shopee.co.id",
            "Accept":         "application/json, text/plain, */*",
            "Content-Type":   "application/json",
            "User-Agent":     self.user_agent,
            "Cookie":         cookie_str,
            "X-Sf-Platform":  "2",
            "Operate-Source": "partnerapp",
            "Origin":         "https://partner.shopee.co.id",
            "Referer":        "https://partner.shopee.co.id/",
        }

    def get_store_dishes(self, store_id: str) -> list[dict]:
        url = f"{SELLER_BASE}/api/seller/store/dishes"
        try:
            resp = self.session.get(url, headers=self._seller_headers(override_entity_id=store_id), timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("catalogs", [])
        except Exception as e:
            print(f"[Shopee API] get_store_dishes error: {e}")
        return []

    def get_store_option_groups(self, store_id: str, dish_ids: list = None) -> list[dict]:
        url = f"{SELLER_BASE}/api/seller/store/option-groups/search"
        payload = {"page_no": 1, "page_size": 100}
        if dish_ids:
            payload["filter"] = {"dish_ids": dish_ids}
        try:
            resp = self.session.post(url, json=payload, headers=self._seller_headers(override_entity_id=store_id), timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("option_groups", [])
        except Exception as e:
            print(f"[Shopee API] get_store_option_groups error: {e}")
        return []

class ShopeeModifyClient:
    def __init__(self, tob_token: str, entity_id: str, extra_cookies: dict = None):
        self.tob_token     = tob_token
        self.entity_id     = entity_id
        self.extra_cookies = extra_cookies or {}
        self.session       = requests.Session()
        self.uploaded_image_hash = ""
        self.last_error = ""

    def _seller_headers(self, override_entity_id: str = None) -> dict:
        eid = override_entity_id or self.entity_id
        cookies = self.extra_cookies.copy()
        cookies["shopee_tob_token"]     = self.tob_token
        cookies["shopee_tob_entity_id"] = eid
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        return {
            "Host":           "foody.shopee.co.id",
            "Accept":         "application/json, text/plain, */*",
            "Content-Type":   "application/json",
            "User-Agent":     USER_AGENT,
            "Cookie":         cookie_str,
            "X-Sf-Platform":  "2",
            "Operate-Source": "partnerapp",
            "Origin":         "https://partner.shopee.co.id",
            "Referer":        "https://partner.shopee.co.id/",
        }

    def _mms_headers(self) -> dict:
        cookies = self.extra_cookies.copy()
        cookies["shopee_tob_token"] = self.tob_token
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        return {
            "Host":           "api.mms.shopee.co.id",
            "Accept":         "application/json, text/plain, */*",
            "Content-Type":   "application/json",
            "User-Agent":     USER_AGENT,
            "Cookie":         cookie_str,
            "X-Sf-Platform":  "2",
            "Operate-Source": "partnerapp",
            "Origin":         "https://partner.shopee.co.id",
            "Referer":        "https://partner.shopee.co.id/",
        }

    @staticmethod
    def _make_request_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _make_sign(prefix: str = "PnjKKY") -> str:
        t = str(int(time.time()))
        combined = f"{prefix}{t}"
        h = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        return f"{t}-{h}"

    def get_stores(self) -> list[dict]:
        url = f"{SELLER_BASE}/api/seller/stores"
        params = {
            "request_id": self._make_request_id(),
            "sign":       self._make_sign()
        }
        try:
            resp = self.session.get(url, headers=self._seller_headers(), params=params, timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("stores", [])
        except Exception as e:
            self.last_error = str(e)
        return []

    def get_store_dishes(self, store_id: str = None) -> list[dict]:
        url = f"{SELLER_BASE}/api/seller/store/dishes"
        try:
            resp = self.session.get(url, headers=self._seller_headers(override_entity_id=store_id), timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("catalogs", [])
        except Exception as e:
            self.last_error = str(e)
        return []

    def get_store_option_groups(self, store_id: str = None, dish_ids: list = None) -> list[dict]:
        url = f"{SELLER_BASE}/api/seller/store/option-groups/search"
        payload = {"page_no": 1, "page_size": 100}
        if dish_ids:
            payload["filter"] = {"dish_ids": dish_ids}
        try:
            resp = self.session.post(url, json=payload, headers=self._seller_headers(override_entity_id=store_id), timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("option_groups", [])
        except Exception as e:
            self.last_error = str(e)
        return []

    def get_dish_detail(self, dish_id: str, store_id: str = None) -> dict | None:
        url = f"{SELLER_BASE}/api/seller/store/dish"
        params = {"dish_id": dish_id}
        try:
            resp = self.session.get(url, headers=self._seller_headers(override_entity_id=store_id), params=params, timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("dish")
        except Exception as e:
            self.last_error = str(e)
        return None

    def _preupload_image(self) -> dict | None:
        payload = {"app_id": 10051}
        try:
            resp = self.session.post(MMS_PREUPLOAD, json=payload, headers=self._mms_headers(), timeout=15)
            data = resp.json()
            if data.get("code") == 0:
                services = data.get("data", {}).get("upload_services", [])
                if services:
                    upload_domain = services[0].get("upload_domain")
                    return {
                        "token":         data["data"]["upload_token"],
                        "img_id":        data["data"]["img_id"],
                        "upload_domain": upload_domain,
                    }
        except Exception as e:
            self.last_error = str(e)
        return None

    def _upload_image_binary(self, upload_domain: str, token: str, img_id: str, image_path: str) -> str | None:
        upload_url = f"{upload_domain}/file/upload"
        headers = {
            "Accept":         "application/json, text/plain, */*",
            "User-Agent":     USER_AGENT,
            "X-Sf-Platform":  "2",
            "Operate-Source": "partnerapp",
        }
        try:
            with open(image_path, "rb") as f:
                img_data = f.read()
            h = hashlib.md5(img_data).hexdigest()
            files = {
                "file": (Path(image_path).name, img_data, "image/jpeg")
            }
            params = {
                "token":  token,
                "img_id": img_id,
                "md5":    h
            }
            resp = self.session.post(upload_url, files=files, params=params, headers=headers, timeout=30)
            if resp.status_code == 200:
                return img_id
        except Exception as e:
            self.last_error = str(e)
        return None

    def upload_image(self, image_path: str) -> str | None:
        pre = self._preupload_image()
        if not pre:
            return None
        return self._upload_image_binary(
            upload_domain=pre["upload_domain"],
            token=pre["token"],
            img_id=pre["img_id"],
            image_path=image_path
        )
