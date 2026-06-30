"""
GrabFood Platform Adapter (Read-Only)
Provides pull_stores, pull_dishes, export_menu, and ping_session using
the Playwright-based Grab API pattern from grab.py.
"""

import os
import json
import time
import pandas as pd
from pathlib import Path
from playwright.sync_api import sync_playwright

from base_adapter import PlatformAdapter


class GrabAdapter(PlatformAdapter):
    platform_name = "grab"

    @property
    def supports_write(self) -> bool:
        return True

    def _resolve_paths(self):
        """Resolve session and credentials paths."""
        menu_dir = Path(__file__).resolve().parents[2]  # menu/
        session_dir = menu_dir / "sessions"
        os.makedirs(session_dir, exist_ok=True)
        creds_path = menu_dir / "credentials.json"
        return menu_dir, session_dir, creds_path

    def _get_credentials(self, outlet=None):
        """Get Grab credentials from outlet or credentials.json."""
        if outlet and outlet.username and outlet.password:
            return outlet.username, outlet.password

        _, _, creds_path = self._resolve_paths()
        if creds_path.exists():
            with open(creds_path) as f:
                creds = json.load(f)
            grab = creds.get("GrabFood", {})
            return grab.get("username", ""), grab.get("password", "")
        return "", ""

    def _launch_context(self, username, headless=True):
        """Launch Playwright browser and return (playwright, browser, context, page, session_path)."""
        _, session_dir, _ = self._resolve_paths()
        session_path = session_dir / f"grab_{username}.json"

        pw = sync_playwright().start()
        browser = pw.chromium.launch(
            headless=headless,
            args=["--disable-extensions", "--disable-component-update"]
        )
        storage_state = str(session_path) if session_path.exists() else None
        context = browser.new_context(
            storage_state=storage_state,
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        return pw, browser, context, page, session_path

    def _call_api(self, page, url, method="GET", headers=None, body=None):
        """Make an API call using the page's fetch context (with cookies)."""
        js_code = """
        async (args) => {
            try {
                const { url, method, headers, body } = args;
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 15000);
                const fetchOpts = {
                    method: method,
                    signal: controller.signal,
                    headers: headers || {},
                    credentials: "include"
                };
                if (body) {
                    fetchOpts.body = typeof body === 'string' ? body : JSON.stringify(body);
                }
                const response = await fetch(url, fetchOpts);
                clearTimeout(timeoutId);
                const status = response.status;
                const text = await response.text();
                try {
                    return { status, data: JSON.parse(text) };
                } catch (e) {
                    return { status, data: text };
                }
            } catch (e) {
                return { status: 0, error: e.toString() };
            }
        }
        """
        for attempt in range(3):
            try:
                if page.is_closed():
                    return {"status": 0, "error": "Page closed"}
                res = page.evaluate(js_code, {
                    "url": url,
                    "method": method,
                    "headers": headers or {},
                    "body": body
                })
                if res is None:
                    res = {"status": 0, "error": "Evaluation returned None"}
                if res.get("status") == 0 and res.get("error"):
                    err_msg = res["error"].lower()
                    if "failed to fetch" in err_msg or "networkerror" in err_msg or "aborted" in err_msg:
                        time.sleep(2)
                        continue
                return res
            except Exception as e:
                print(f"[GrabAdapter] _call_api error on attempt {attempt}: {e}")
                time.sleep(2)
                continue
        return {"status": 0, "error": "Max retries reached in API call"}

    def _ensure_login(self, page, username, password, session_path):
        """Ensure we are logged in to Grab merchant portal. Returns True on success."""
        is_on_login_page = True

        if session_path.exists():
            try:
                page.goto("https://merchant.grab.com/dashboard", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(1000)
                current_url = page.url.lower()
                if ("dashboard" in current_url or "portal" in current_url) and "login" not in current_url and "saved-accounts" not in current_url:
                    is_on_login_page = False
            except Exception:
                pass

        if not is_on_login_page:
            return True

        print(f"[GrabAdapter] Memulai login untuk {username}...")
        CLEAN_LOGIN_URL = "https://weblogin.grab.com/merchant/login?service_id=MEXUSERS&redirect=https%3A%2F%2Fmerchant.grab.com%2Fportal"
        try:
            page.goto(CLEAN_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            # Handle saved accounts
            is_saved_accounts = "saved-accounts" in page.url
            if is_saved_accounts:
                if username.lower() in page.content().lower():
                    continue_btn = page.locator('button:has-text("Continue"), button:has-text("Lanjut")')
                    if continue_btn.count() > 0:
                        continue_btn.first.click()
                        page.wait_for_timeout(2000)
                else:
                    use_other = page.locator('a:has-text("Use another account"), button:has-text("Use another account"), a:has-text("Gunakan akun lain")')
                    if use_other.count() > 0:
                        use_other.first.click()
                        page.wait_for_timeout(2000)

            # Fill username
            user_selectors = ['input[name="username"]', '#username', 'input[type="text"]', 'input[type="email"]']
            user_field = None
            for sel in user_selectors:
                elements = page.locator(sel)
                if elements.count() > 0:
                    for i in range(elements.count()):
                        el = elements.nth(i)
                        try:
                            if el.is_visible(timeout=2000) and el.is_enabled():
                                user_field = el
                                break
                        except:
                            continue
                if user_field:
                    break

            if user_field:
                user_field.click()
                user_field.fill(username)
                page.wait_for_timeout(500)
                continue_btn = page.locator('button:has-text("Continue"), button:has-text("Lanjut")').first
                if continue_btn.count() > 0 and continue_btn.is_visible():
                    continue_btn.click()
                else:
                    page.keyboard.press("Enter")
                page.wait_for_timeout(2500)

            # Fill password
            pwd_selector = 'input[type="password"], #password'
            try:
                page.wait_for_selector(pwd_selector, timeout=15000)
            except:
                pass

            if page.locator(pwd_selector).count() > 0:
                page.fill(pwd_selector, password)
                page.wait_for_timeout(500)
                page.keyboard.press("Enter")
                page.wait_for_timeout(3000)
                try:
                    page.wait_for_url(lambda u: "login" not in u.lower() and "saved-accounts" not in u, timeout=20000)
                except:
                    pass

            if "login" in page.url.lower():
                return False

            try:
                page.goto("https://merchant.grab.com/dashboard", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
            except:
                pass

            return True
        except Exception as e:
            print(f"[GrabAdapter] Login failed: {e}")
            return False

    def _resolve_mgid_for_store(self, page, store_id):
        """
        Resolve the correct Merchant Group ID for a given store_id.
        Returns (mgid, merchant_name) or (None, None).
        """
        profile_resp = self._call_api(page, "https://merchant.grab.com/troy/user-profile/v1/merchant-selector")
        if profile_resp.get("status") != 200:
            return None, None

        merchants_list = profile_resp.get("data", {}).get("merchants", [])
        if not merchants_list:
            return None, None

        for m_group in merchants_list:
            cand_mgid = m_group.get("id")
            offset = 0
            limit = 100

            while True:
                url = f"https://portal.grab.com/foodtroy/v1/ID/merchant-groups/catalog-stores?offset={offset}&limit={limit}&isWithItemPhotoCount=true"
                headers = {
                    "Accept": "application/json",
                    "x-api-source": "food-trx",
                    "requestsource": "troyPortal",
                    "merchantgroupid": cand_mgid,
                }
                resp = self._call_api(page, url, headers=headers)
                if resp.get("status") == 200:
                    merchants = resp.get("data", {}).get("merchants", [])
                    for m in merchants:
                        if str(m.get("merchantID")).strip().lower() == store_id.lower():
                            return cand_mgid, m.get("merchantName", "")
                    metadata = resp.get("data", {}).get("metadata", {})
                    if not metadata or not metadata.get("hasMore") or not merchants:
                        break
                    offset += limit
                else:
                    break

        # Fallback to first group
        return merchants_list[0].get("id"), None

    def pull_stores(self, username: str, password: str) -> list[dict]:
        """Pull semua store dari akun Grab."""
        pw, browser, context, page, session_path = self._launch_context(username)
        try:
            if not self._ensure_login(page, username, password, session_path):
                print("[GrabAdapter] Login gagal")
                return []

            # Get merchant groups
            profile_resp = self._call_api(page, "https://merchant.grab.com/troy/user-profile/v1/merchant-selector")
            if profile_resp.get("status") != 200:
                return []

            merchants_list = profile_resp.get("data", {}).get("merchants", [])
            context.storage_state(path=str(session_path))

            all_stores = []
            for m_group in merchants_list:
                mgid = m_group.get("id")
                offset = 0
                limit = 100

                while True:
                    url = f"https://portal.grab.com/foodtroy/v1/ID/merchant-groups/catalog-stores?offset={offset}&limit={limit}&isWithItemPhotoCount=true"
                    headers = {
                        "Accept": "application/json",
                        "x-api-source": "food-trx",
                        "requestsource": "troyPortal",
                        "merchantgroupid": mgid,
                    }
                    resp = self._call_api(page, url, headers=headers)
                    if resp.get("status") == 200:
                        merchants = resp.get("data", {}).get("merchants", [])
                        for m in merchants:
                            all_stores.append({
                                "store_id": str(m.get("merchantID")),
                                "merchant_name": m.get("merchantName", ""),
                                "mgid": mgid,
                            })
                        metadata = resp.get("data", {}).get("metadata", {})
                        if not metadata or not metadata.get("hasMore") or not merchants:
                            break
                        offset += limit
                    else:
                        break

            print(f"[GrabAdapter] Total stores fetched: {len(all_stores)}")
            return all_stores
        finally:
            try:
                browser.close()
                pw.stop()
            except:
                pass

    def pull_dishes(self, outlet) -> list[dict]:
        """Pull menu data dari Grab API dan normalize ke format standar."""
        username, password = self._get_credentials(outlet)
        pw, browser, context, page, session_path = self._launch_context(username)

        try:
            if not self._ensure_login(page, username, password, session_path):
                raise Exception("Login Grab gagal")

            mgid = getattr(outlet, 'mgid', None)
            merchant_name = outlet.merchant_name

            if not mgid:
                mgid, resolved_name = self._resolve_mgid_for_store(page, outlet.store_id)
                if resolved_name:
                    merchant_name = resolved_name

            if not mgid:
                raise Exception("Tidak dapat resolve Merchant Group ID")

            context.storage_state(path=str(session_path))

            # Fetch menu
            menu_headers = {
                "Accept": "application/json",
                "merchantgroupid": mgid,
                "merchantid": outlet.store_id,
                "requestsource": "troyPortal",
                "x-api-source": "food-max-api",
            }
            menu_resp = self._call_api(page, "https://api.grab.com/food/merchant/v2/menu", headers=menu_headers)
            if menu_resp.get("status") != 200:
                raise Exception(f"Menu API failed (Status {menu_resp.get('status')}): {menu_resp.get('error') or menu_resp.get('data')}")

            menu_data = menu_resp.get("data", {})
            categories = menu_data.get("categories", [])

            # Normalize to standard format
            result = []
            for idx, cat in enumerate(categories):
                cat_active = cat.get("availableStatus") == 1
                normalized_cat = {
                    "id": cat.get("categoryID", f"grab_cat_{idx}"),
                    "name": cat.get("categoryName", "").strip(),
                    "sequence": cat.get("sortOrder", idx),
                    "items": [],
                }
                for item in cat.get("items", []):
                    price_in_min = item.get("priceInMin", 0)
                    price_rp = float(price_in_min) / 100.0 if price_in_min else 0.0
                    item_available = item.get("availableStatus") == 1

                    img_url = item.get("imageURL") or ""
                    if not img_url and item.get("imageURLs"):
                        img_url = item["imageURLs"][0]

                    normalized_cat["items"].append({
                        "id": item.get("itemID", ""),
                        "name": item.get("itemName", "").strip(),
                        "price_rp": price_rp,
                        "description": item.get("description", "").strip(),
                        "available": item_available and cat_active,
                        "show": True,  # Grab doesn't have a separate show toggle
                        "image_url": img_url,
                        "stock_type": 0,
                        "stock_limit_current": 0,
                    })
                result.append(normalized_cat)

            print(f"[GrabAdapter] Menu fetched: {sum(len(c['items']) for c in result)} items in {len(result)} categories")
            return result
        finally:
            try:
                browser.close()
                pw.stop()
            except:
                pass

    def export_menu(self, outlet) -> tuple:
        """Export menu GrabFood sebagai (df_items, df_mods) DataFrames."""
        username, password = self._get_credentials(outlet)
        pw, browser, context, page, session_path = self._launch_context(username)

        try:
            if not self._ensure_login(page, username, password, session_path):
                raise Exception("Login Grab gagal")

            mgid = getattr(outlet, 'mgid', None)
            merchant_name = outlet.merchant_name

            if not mgid:
                mgid, resolved_name = self._resolve_mgid_for_store(page, outlet.store_id)
                if resolved_name:
                    merchant_name = resolved_name

            if not mgid:
                raise Exception("Tidak dapat resolve Merchant Group ID")

            context.storage_state(path=str(session_path))

            # Fetch menu
            menu_headers = {
                "Accept": "application/json",
                "merchantgroupid": mgid,
                "merchantid": outlet.store_id,
                "requestsource": "troyPortal",
                "x-api-source": "food-max-api",
            }
            menu_resp = self._call_api(page, "https://api.grab.com/food/merchant/v2/menu", headers=menu_headers)
            if menu_resp.get("status") != 200:
                raise Exception(f"Menu API failed (Status {menu_resp.get('status')})")

            menu_data = menu_resp.get("data", {})
            categories = menu_data.get("categories", [])
            modifier_groups = menu_data.get("modifierGroups", [])

            # Build modifier group index
            mod_group_map = {}
            for group in modifier_groups:
                gid = group.get("modifierGroupID")
                if gid:
                    mod_group_map[gid] = group

            all_dishes = []
            modifier_rows = []

            for cat in categories:
                cat_name = cat.get("categoryName", "").strip()
                cat_active = cat.get("availableStatus") == 1

                for item in cat.get("items", []):
                    item_name = item.get("itemName", "").strip()
                    price_in_min = item.get("priceInMin", 0)
                    item_price = float(price_in_min) / 100.0 if price_in_min else 0.0
                    item_available = item.get("availableStatus") == 1
                    ketersediaan = "Tersedia" if (item_available and cat_active) else "Habis"

                    img_url = item.get("imageURL") or ""
                    if not img_url and item.get("imageURLs"):
                        img_url = item["imageURLs"][0]

                    linked_mod_ids = item.get("linkedModifierGroupIDs") or []
                    mod_groups_count = len(linked_mod_ids)
                    total_mods = 0

                    for gid in linked_mod_ids:
                        group = mod_group_map.get(gid)
                        if not group:
                            continue
                        group_name = group.get("modifierGroupName", "").strip()
                        min_sel = group.get("selectionRangeMin", 0)
                        max_sel = group.get("selectionRangeMax", 0)
                        tipe = "Pilihan Tunggal" if max_sel == 1 else "Pilihan Ganda"

                        for mod in group.get("modifiers", []):
                            total_mods += 1
                            mod_price = float(mod.get("priceInMin", 0)) / 100.0
                            modifier_rows.append({
                                "link_outlet": f"https://merchant.grab.com/food/menu/{outlet.store_id}",
                                "nama_panjang": merchant_name,
                                "store_id": outlet.store_id,
                                "nama_item": item_name,
                                "nama_modifier_group": group_name,
                                "nama_modifier": mod.get("modifierName", "").strip(),
                                "tipe_modifier": tipe,
                                "minimal": min_sel,
                                "maksimal": max_sel,
                                "harga_modifier": mod_price,
                                "ketersediaan_modifier": "Tersedia" if mod.get("availableStatus") == 1 else "Habis",
                            })

                    all_dishes.append({
                        "link_outlet": f"https://merchant.grab.com/food/menu/{outlet.store_id}",
                        "nama_panjang": merchant_name,
                        "store_id": outlet.store_id,
                        "nama_kategori": cat_name,
                        "nama_item": item_name,
                        "jumlah_terjual": item.get("soldQuantity", 0),
                        "jumlah_modifier_group": mod_groups_count,
                        "jumlah_modifier": total_mods,
                        "deskripsi_item": item.get("description", "").strip(),
                        "harga_sebelum_promo": item_price,
                        "harga_setelah_promo": item_price,
                        "promo": "",
                        "ketersediaan": ketersediaan,
                        "link_foto": img_url,
                    })

            # Build DataFrames
            item_cols = [
                "Link outlet", "Nama panjang", "Store ID",
                "Nama kategori", "Nama item", "Jumlah terjual",
                "Jumlah modifier group", "Jumlah modifier", "Deskripsi item",
                "Harga item sebelum promo", "Harga item setelah promo",
                "Promo", "Ketersediaan item", "Link foto",
            ]
            item_data = [[
                d["link_outlet"], d["nama_panjang"], d["store_id"],
                d["nama_kategori"], d["nama_item"], d["jumlah_terjual"],
                d["jumlah_modifier_group"], d["jumlah_modifier"], d["deskripsi_item"],
                d["harga_sebelum_promo"], d["harga_setelah_promo"],
                d["promo"], d["ketersediaan"], d["link_foto"],
            ] for d in all_dishes]

            mod_cols = [
                "Link outlet", "Nama panjang", "Store ID",
                "Nama item", "Nama modifier group", "Nama modifier",
                "Tipe modifier", "Minimal", "Maksimal",
                "Harga modifier", "Ketersediaan modifier",
            ]
            mod_data = [[
                m["link_outlet"], m["nama_panjang"], m["store_id"],
                m["nama_item"], m["nama_modifier_group"], m["nama_modifier"],
                m["tipe_modifier"], m["minimal"], m["maksimal"],
                m["harga_modifier"], m["ketersediaan_modifier"],
            ] for m in modifier_rows]

            return pd.DataFrame(item_data, columns=item_cols), pd.DataFrame(mod_data, columns=mod_cols)
        finally:
            try:
                browser.close()
                pw.stop()
            except:
                pass

    def ping_session(self, outlet) -> dict:
        """Cek apakah session Grab masih aktif."""
        username, password = self._get_credentials(outlet)
        _, session_dir, _ = self._resolve_paths()
        session_path = session_dir / f"grab_{username}.json"

        if not session_path.exists():
            return {"active": False, "msg": "No session file found"}

        pw = None
        browser = None
        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                storage_state=str(session_path),
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
            )
            page = context.new_page()
            page.goto("https://merchant.grab.com/dashboard", wait_until="domcontentloaded", timeout=10000)
            page.wait_for_timeout(1000)

            current_url = page.url.lower()
            if ("dashboard" in current_url or "portal" in current_url) and "login" not in current_url:
                return {"active": True, "msg": "Active"}
            else:
                return {"active": False, "msg": "Session expired (redirected to login)"}
        except Exception as e:
            return {"active": False, "msg": str(e)}
        finally:
            try:
                if browser:
                    browser.close()
                if pw:
                    pw.stop()
            except:
                pass

    def sync_changes(self, db, outlet, pending_categories, pending_dishes) -> list[str]:
        """Push pending edits (categories/dishes) to GrabFood platform."""
        sync_errors = []
        username, password = self._get_credentials(outlet)
        pw, browser, context, page, session_path = self._launch_context(username)
        
        try:
            if not self._ensure_login(page, username, password, session_path):
                raise Exception("Login Grab gagal")
                
            mgid = getattr(outlet, 'mgid', None)
            if not mgid:
                mgid, resolved_name = self._resolve_mgid_for_store(page, outlet.store_id)
                
            if not mgid:
                raise Exception("Tidak dapat resolve Merchant Group ID")
                
            # 1. Sync Categories
            for cat in pending_categories:
                err_msg = f"Kategori '{cat.name}': Platform GrabFood saat ini hanya mendukung edit detail item."
                print(f"  [GrabSync] {err_msg}")
                cat.sync_status = "failed"
                sync_errors.append(err_msg)
                db.commit()

            # 2. Sync Dishes
            if pending_dishes:
                # Fetch full menu tree from GrabFood API to retrieve complete item dictionaries
                menu_headers = {
                    "Accept": "application/json",
                    "merchantgroupid": mgid,
                    "merchantid": outlet.store_id,
                    "requestsource": "troyPortal",
                    "x-api-source": "food-max-api",
                }
                menu_resp = self._call_api(page, "https://api.grab.com/food/merchant/v2/menu", headers=menu_headers)
                if menu_resp.get("status") != 200:
                    raise Exception(f"Gagal mengambil menu dari Grab API: {menu_resp.get('error') or menu_resp.get('data')}")
                    
                menu_data = menu_resp.get("data", {})
                categories = menu_data.get("categories", [])
                
                # Build index of items by ID
                item_map = {}
                cat_map = {}
                for cat in categories:
                    cat_id = cat.get("categoryID")
                    for item in cat.get("items", []):
                        item_id = item.get("itemID")
                        if item_id:
                            item_map[item_id] = item
                            cat_map[item_id] = cat_id

                for dish in pending_dishes:
                    if dish.sync_status == "pending_create":
                        err_msg = f"Menu baru '{dish.name}': Platform GrabFood saat ini hanya mendukung edit detail item yang sudah ada."
                        print(f"  [GrabSync] {err_msg}")
                        dish.sync_status = "failed"
                        sync_errors.append(err_msg)
                        db.commit()
                        continue
                        
                    if dish.sync_status == "pending_metadata":
                        item_obj = item_map.get(dish.id)
                        cat_id = cat_map.get(dish.id)
                        if not item_obj or not cat_id:
                            err_msg = f"Menu '{dish.name}' (ID: {dish.id}) tidak ditemukan di GrabFood."
                            print(f"  [GrabSync] {err_msg}")
                            dish.sync_status = "failed"
                            sync_errors.append(err_msg)
                            db.commit()
                            continue
                            
                        # Update fields
                        item_obj["itemName"] = dish.name
                        item_obj["description"] = dish.description or ""
                        item_obj["priceInMin"] = int(round(dish.price_rp * 100))
                        item_obj["availableStatus"] = 1 if dish.available else 0
                        
                        # 1. Validation
                        val_headers = {
                            "Accept": "application/json",
                            "merchantgroupid": mgid,
                            "merchantid": outlet.store_id,
                            "requestsource": "troyPortal",
                            "content-type": "application/json",
                            "x-api-source": "food-max-api",
                        }
                        val_payload = {
                            "item": item_obj,
                            "categoryID": cat_id
                        }
                        val_resp = self._call_api(
                            page, 
                            "https://api.grab.com/food/merchant/v2/item-validation", 
                            method="POST", 
                            headers=val_headers, 
                            body=val_payload
                        )
                        
                        if val_resp.get("status") not in [200, 204]:
                            err_msg = f"Validasi gagal untuk '{dish.name}': {val_resp.get('error') or val_resp.get('data')}"
                            print(f"  [GrabSync] {err_msg}")
                            dish.sync_status = "failed"
                            sync_errors.append(err_msg)
                            db.commit()
                            continue
                            
                        # 2. Upsert
                        upsert_resp = self._call_api(
                            page, 
                            "https://api.grab.com/food/merchant/v2/upsert-item", 
                            method="POST", 
                            headers=val_headers, 
                            body=val_payload
                        )
                        
                        if upsert_resp.get("status") == 200:
                            print(f"  [GrabSync] Menu '{dish.name}' berhasil diperbarui via Grab API")
                            dish.sync_status = "synced"
                        else:
                            err_msg = f"Gagal memperbarui menu '{dish.name}': {upsert_resp.get('error') or upsert_resp.get('data')}"
                            print(f"  [GrabSync] {err_msg}")
                            dish.sync_status = "failed"
                            sync_errors.append(err_msg)
                        db.commit()

            # Save session state
            context.storage_state(path=str(session_path))
            return sync_errors
        finally:
            try:
                browser.close()
                pw.stop()
            except:
                pass
