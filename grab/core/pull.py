import os
import json
import re
import sys
import time
import pandas as pd
from pathlib import Path
from playwright.sync_api import sync_playwright

def extract_grab_menu(store_metadata: dict, output_dir: str):
    """
    Extracts menu for GrabFood by logging into merchant portal and calling the menu API.
    """
    store_id = store_metadata.get('store_id', '')
    # Fallback to nama_resto_final or nama_outlet
    m_name = store_metadata.get('merchant_name', '')
    if not m_name or m_name.lower() == 'nan' or m_name == '-':
        nama_resto = store_metadata.get('nama_resto_final') or store_metadata.get('nama_outlet') or ''
    else:
        nama_resto = m_name
        
    username = store_metadata.get('username') or ''
    password = store_metadata.get('password') or ''
    
    # Clean the store ID to be safe
    store_id = str(store_id).strip()
    
    print(f"\n[GrabFood Menu Extractor]")
    print(f"[-] Target Outlet: {nama_resto} ({store_id})")
    
    # 1. Resolve Credentials
    if not username or not password:
        creds_paths = [
            "/home/akbarhann/project/task-weekly/menu/menu_automate/credentials.json",
            "/home/akbarhann/project/task-weekly/menu/credentials.json"
        ]
        for cp in creds_paths:
            if os.path.exists(cp):
                try:
                    with open(cp, "r") as f:
                        creds = json.load(f)
                    grab_creds = creds.get("GrabFood", {})
                    username = grab_creds.get("username", username)
                    password = grab_creds.get("password", password)
                    if username and password:
                        break
                except Exception as e:
                    print(f"   [!] Gagal memuat kredensial dari {cp}: {e}")

    if not username or not password:
        print("[!] GrabFood: Username atau Password kosong.")
        return False, "Username atau Password kosong dalam metadata toko dan credentials.json."

    print(f"[-] Akun Login: {username}")
    
    # 2. Setup Session Path
    menu_dir = Path(__file__).resolve().parents[2]
    session_dir = menu_dir / "sessions"
    os.makedirs(session_dir, exist_ok=True)
    session_path = session_dir / f"grab_{username}.json"
    
    # Load headless config
    headless_env = True
    try:
        for parent in Path(__file__).resolve().parents:
            config_file = parent / "config.json"
            if config_file.exists():
                with open(config_file, "r") as f:
                    headless_env = json.load(f).get("headless_grab", True)
                break
    except Exception:
        pass
        
    print(f"[*] Meluncurkan browser (headless={headless_env})...")
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=headless_env,
                args=[
                    "--disable-extensions",
                    "--disable-component-update"
                ]
            )
            
            storage_state = str(session_path) if session_path.exists() else None
            context = browser.new_context(
                storage_state=storage_state,
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # Helper for API call inside page context
            def call_api(url, method="GET", headers=None):
                headers_json = json.dumps(headers or {})
                js_code = f"""
                async () => {{
                    try {{
                        const controller = new AbortController();
                        const timeoutId = setTimeout(() => controller.abort(), 15000);
                        
                        const response = await fetch("{url}", {{
                            method: "{method}",
                            signal: controller.signal,
                            headers: {headers_json},
                            credentials: "include"
                        }});
                        clearTimeout(timeoutId);
                        const status = response.status;
                        const text = await response.text();
                        try {{
                            return {{ status, data: JSON.parse(text) }};
                        }} catch (e) {{
                            return {{ status, data: text }};
                        }}
                    }} catch (e) {{
                        return {{ status: 0, error: e.toString() }};
                    }}
                }}
                """
                for attempt in range(3):
                    try:
                        if page.is_closed():
                            return {"status": 0, "error": "Page closed"}
                        res = page.evaluate(js_code)
                        if res is None:
                            res = {"status": 0, "error": "Evaluation returned None"}
                        if res.get("status") == 0 and res.get("error"):
                            err_msg = res["error"].lower()
                            if "failed to fetch" in err_msg or "networkerror" in err_msg or "aborted" in err_msg:
                                time.sleep(2)
                                continue
                        return res
                    except Exception:
                        time.sleep(2)
                        continue
                return {"status": 0, "error": "Max retries reached in API call"}

            # Helper to check errors on page
            def check_block_and_errors():
                block_texts = ["blocked due to multiple invalid login attempts", "try again later", "coba lagi nanti", "diblokir sementara"]
                page_content = page.content()
                for text in block_texts:
                    if text.lower() in page_content.lower():
                        raise ValueError("Akun Grab diblokir sementara.")
                error_texts = ["Make sure you have the right username", "attempts left", "salah memasukkan password", "Kredensial tidak valid", "Invalid credentials", "Wrong credentials", "Incorrect password", "Kata sandi salah"]
                for text in error_texts:
                    if text.lower() in page_content.lower():
                        raise ValueError("Kredensial Grab salah.")

            # Check existing session
            is_on_login_page = True
            if storage_state:
                print(f"[*] Memeriksa sesi aktif untuk {username}...")
                try:
                    page.goto("https://merchant.grab.com/dashboard", wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(1000)
                    current_url = page.url.lower()
                    if ("dashboard" in current_url or "portal" in current_url) and "login" not in current_url and "saved-accounts" not in current_url:
                        is_on_login_page = False
                except Exception as e:
                    print(f"  [!] Session check timed out or failed: {e}")
                    
            # Perform Login if not active
            if is_on_login_page:
                print("[*] Sesi tidak aktif atau teralihkan ke login. Memulai alur login...")
                CLEAN_LOGIN_URL = "https://weblogin.grab.com/merchant/login?service_id=MEXUSERS&redirect=https%3A%2F%2Fmerchant.grab.com%2Fportal"
                try:
                    page.goto(CLEAN_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(3000)
                    check_block_and_errors()
                    
                    # Handle saved accounts welcome back page
                    is_saved_accounts = "saved-accounts" in page.url
                    welcome_back_locator = page.locator('h1:has-text("Welcome back"), h2:has-text("Welcome back"), div:has-text("Welcome back")')
                    if is_saved_accounts or welcome_back_locator.count() > 0:
                        if username.lower() in page.content().lower():
                            print("  [Login] Saved account cocok, klik Continue...")
                            continue_btn = page.locator('button:has-text("Continue"), button:has-text("Lanjut")')
                            if continue_btn.count() > 0:
                                continue_btn.first.click()
                                try:
                                    page.wait_for_selector('input[type="password"], .dashboard, .portal-content', timeout=10000)
                                except:
                                    pass
                        else:
                            print("  [Login] Saved account tidak cocok, hapus cookie...")
                            context.clear_cookies()
                            page.goto(CLEAN_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                            page.wait_for_timeout(2000)
                    
                    check_block_and_errors()
                    
                    # Fill Username
                    user_selectors = ['input[type="email"]', 'input[name="email"]', 'input[type="text"]', '#email', '#username']
                    user_field = None
                    for sel in user_selectors:
                        try:
                            el = page.locator(sel).first
                            if el.is_visible(timeout=2000) and el.is_enabled():
                                user_field = el
                                break
                        except:
                            continue
                    
                    if user_field:
                        user_field.click()
                        user_field.fill(username)
                        page.wait_for_timeout(500)
                        
                        # Verify value
                        if user_field.input_value().strip() != username.strip():
                            user_field.click()
                            page.keyboard.press("Control+A")
                            page.keyboard.press("Backspace")
                            page.keyboard.type(username, delay=50)
                            page.wait_for_timeout(500)
                            
                        continue_btn = page.locator('button:has-text("Continue"), button:has-text("Lanjut")').first
                        if continue_btn.count() > 0 and continue_btn.is_visible():
                            continue_btn.click()
                        else:
                            page.keyboard.press("Enter")
                        page.wait_for_timeout(2500)
                        check_block_and_errors()
                    
                    # Fill Password
                    pwd_selector = 'input[type="password"], #password'
                    try:
                        page.wait_for_selector(pwd_selector, timeout=15000)
                    except:
                        continue_btns = page.locator('button:has-text("Continue"), button:has-text("Next"), button:has-text("Lanjut")')
                        if continue_btns.count() > 0:
                            continue_btns.first.click()
                            try:
                                page.wait_for_selector(pwd_selector, timeout=10000)
                            except:
                                pass
                    
                    check_block_and_errors()
                    if page.locator(pwd_selector).count() > 0:
                        page.fill(pwd_selector, password)
                        page.wait_for_timeout(500)
                        page.keyboard.press("Enter")
                        page.wait_for_timeout(3000)
                        check_block_and_errors()
                        
                        try:
                            page.wait_for_url(lambda u: "login" not in u.lower() and "saved-accounts" not in u, timeout=20000)
                        except:
                            pass
                            
                    # Verify we logged in
                    if "login" in page.url.lower():
                        return False, "Gagal login ke Grab portal (URL masih di halaman login)."
                    
                    # Navigate to dashboard to ensure cookie/domain consistency
                    try:
                        page.goto("https://merchant.grab.com/dashboard", wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(2000)
                    except:
                        pass
                        
                except Exception as e:
                    return False, f"Proses login Grab gagal: {e}"

            # 3. Get Merchant Group ID (MGID)
            print("[*] Mengambil profil merchant...")
            profile_resp = call_api("https://merchant.grab.com/troy/user-profile/v1/merchant-selector")
            if profile_resp.get("status") != 200:
                return False, f"Gagal mendapatkan profil merchant (Status {profile_resp.get('status')}): {profile_resp.get('data')}"
                
            merchants_list = profile_resp.get("data", {}).get("merchants", [])
            if not merchants_list:
                return False, "Tidak ditemukan merchant dalam profil akun."
                
            mgid = None
            nama_resto_actual = nama_resto
            
            # Cari merchant group ID yang memiliki store_id target
            for m_group in merchants_list:
                cand_mgid = m_group.get("id")
                print(f"  [*] Memeriksa Merchant Group: {m_group.get('display_name')} ({cand_mgid})...")
                
                offset = 0
                limit = 100
                found_in_group = False
                
                while True:
                    stores_url = f"https://portal.grab.com/foodtroy/v1/ID/merchant-groups/catalog-stores?offset={offset}&limit={limit}&isWithItemPhotoCount=true"
                    stores_headers = {
                        "Accept": "application/json",
                        "x-api-source": "food-trx",
                        "requestsource": "troyPortal",
                        "merchantgroupid": cand_mgid
                    }
                    stores_resp = call_api(stores_url, headers=stores_headers)
                    if stores_resp.get("status") == 200:
                        merchants = stores_resp.get("data", {}).get("merchants", [])
                        for m in merchants:
                            if str(m.get("merchantID")).strip().lower() == store_id.lower():
                                nama_resto_actual = m.get("merchantName", nama_resto)
                                mgid = cand_mgid
                                found_in_group = True
                                break
                        if found_in_group:
                            break
                        metadata = stores_resp.get("data", {}).get("metadata", {})
                        if not metadata or not metadata.get("hasMore") or not merchants:
                            break
                        offset += limit
                    else:
                        break
                
                if found_in_group:
                    print(f"  [+] Target store ditemukan di group: {m_group.get('display_name')} ({mgid})")
                    break
            
            if not mgid:
                mgid = merchants_list[0].get("id")
                print(f"  [!] Target store tidak ditemukan di group mana pun. Menggunakan fallback MGID: {mgid}")
                
                # Coba cari nama outlet menggunakan fallback group
                stores_url = "https://portal.grab.com/foodtroy/v1/ID/merchant-groups/catalog-stores?offset=0&limit=100&isWithItemPhotoCount=true"
                stores_headers = {
                    "Accept": "application/json",
                    "x-api-source": "food-trx",
                    "requestsource": "troyPortal",
                    "merchantgroupid": mgid
                }
                stores_resp = call_api(stores_url, headers=stores_headers)
                if stores_resp.get("status") == 200:
                    merchants = stores_resp.get("data", {}).get("merchants", [])
                    for m in merchants:
                        if str(m.get("merchantID")).strip().lower() == store_id.lower():
                            nama_resto_actual = m.get("merchantName", nama_resto)
                            break
            
            print(f"  [+] Merchant target berhasil diidentifikasi: {nama_resto_actual}")
            
            # Save storage state
            context.storage_state(path=str(session_path))
            print("  [+] Sesi berhasil disimpan.")

            # 5. Fetch Menu Data
            menu_url = "https://api.grab.com/food/merchant/v2/menu"
            menu_headers = {
                "Accept": "application/json",
                "merchantgroupid": mgid,
                "merchantid": store_id,
                "requestsource": "troyPortal",
                "x-api-source": "food-max-api"
            }
            print(f"[*] Mengambil data menu GrabFood untuk store ID: {store_id}...")
            menu_resp = call_api(menu_url, headers=menu_headers)
            if menu_resp.get("status") != 200:
                err_details = menu_resp.get("error") or menu_resp.get("data")
                return False, f"Gagal mengambil API menu GrabFood (Status {menu_resp.get('status')}): {err_details}"
                
            menu_data = menu_resp.get("data", {})
            
            # 6. Save raw response
            api_dir = menu_dir / "GrabFood" / "API"
            os.makedirs(api_dir, exist_ok=True)
            json_path = api_dir / f"menu-response-{store_id}.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(menu_data, f, indent=4)
            print(f"  [+] Response API berhasil disimpan ke: {json_path}")
            
            # 7. Parse Menu & Modifiers
            categories = menu_data.get("categories", [])
            modifier_groups = menu_data.get("modifierGroups", [])
            
            # Build modifier group index
            mod_group_map = {}
            for group in modifier_groups:
                group_id = group.get("modifierGroupID")
                if group_id:
                    mod_group_map[group_id] = group
                    
            all_dishes = []
            modifier_rows = []
            
            for cat in categories:
                cat_name = cat.get("categoryName", "").strip()
                cat_active = cat.get("availableStatus") == 1
                
                items = cat.get("items", [])
                for item in items:
                    item_name = item.get("itemName", "").strip()
                    item_desc = item.get("description", "").strip()
                    
                    # Price parsing
                    price_in_min = item.get("priceInMin", 0)
                    item_price = float(price_in_min) / 100.0 if price_in_min else 0.0
                    
                    # Availability
                    item_available = item.get("availableStatus") == 1
                    ketersediaan = "Tersedia" if (item_available and cat_active) else "Habis"
                    
                    img_url = item.get("imageURL") or ""
                    if not img_url and item.get("imageURLs"):
                        img_url = item["imageURLs"][0]
                        
                    linked_mod_ids = item.get("linkedModifierGroupIDs") or []
                    mod_groups_count = len(linked_mod_ids)
                    total_modifiers_count = 0
                    
                    for group_id in linked_mod_ids:
                        group = mod_group_map.get(group_id)
                        if not group:
                            continue
                            
                        group_name = group.get("modifierGroupName", "").strip()
                        min_sel = group.get("selectionRangeMin", 0)
                        max_sel = group.get("selectionRangeMax", 0)
                        tipe_modifier = "Pilihan Tunggal" if max_sel == 1 else "Pilihan Ganda"
                        
                        mods_list = group.get("modifiers") or []
                        total_modifiers_count += len(mods_list)
                        
                        for mod in mods_list:
                            mod_name = mod.get("modifierName", "").strip()
                            mod_price_in_min = mod.get("priceInMin", 0)
                            mod_price = float(mod_price_in_min) / 100.0 if mod_price_in_min else 0.0
                            
                            mod_available = mod.get("availableStatus") == 1
                            mod_ketersediaan = "Tersedia" if mod_available else "Habis"
                            
                            modifier_rows.append({
                                'link_outlet': f"https://merchant.grab.com/food/menu/{store_id}",
                                'nama_panjang': nama_resto_actual,
                                'nama_pendek': nama_resto_actual,
                                'store_id': store_id,
                                'nama_item': item_name,
                                'nama_modifier_group': group_name,
                                'nama_modifier': mod_name,
                                'tipe_modifier': tipe_modifier,
                                'minimal': min_sel,
                                'maksimal': max_sel,
                                'harga_modifier': mod_price,
                                'ketersediaan_modifier': mod_ketersediaan
                            })
                            
                    dish_obj = {
                        'link_outlet': f"https://merchant.grab.com/food/menu/{store_id}",
                        'nama_panjang': nama_resto_actual,
                        'nama_pendek': nama_resto_actual,
                        'store_id': store_id,
                        'nama_kategori': cat_name,
                        'nama_item': item_name,
                        'jumlah_terjual': item.get("soldQuantity", 0),
                        'jumlah_modifier_group': mod_groups_count,
                        'jumlah_modifier': total_modifiers_count,
                        'deskripsi_item': item_desc,
                        'harga_sebelum_promo': item_price,
                        'harga_setelah_promo': item_price,
                        'promo': "",
                        'harga_flash_sale': "",
                        'promo_flash_sale': "",
                        'stok_flash_sale': "",
                        'ketersediaan': ketersediaan,
                        'link_foto': img_url
                    }
                    all_dishes.append(dish_obj)
                    
            # 8. Build DataFrames
            item_cols = [
                'Link outlet', 'Nama panjang', 'Nama pendek (ShopeeFood)', 'Store ID',
                'Nama kategori', 'Nama item', 'Jumlah terjual', 'Jumlah modifier group',
                'Jumlah modifier', 'Deskripsi item', 'Harga item sebelum promo (harga coret)',
                'Harga item setelah promo (harga coret)', 'Nominal atau persentase promo (harga coret)',
                'Harga flash sale', 'Persentase promo flash sale', 'Stok flash sale',
                'Ketersediaan item', 'Link foto'
            ]
            
            item_data = []
            for d in all_dishes:
                item_data.append([
                    d['link_outlet'], d['nama_panjang'], d['nama_pendek'], d['store_id'],
                    d['nama_kategori'], d['nama_item'], d['jumlah_terjual'], d['jumlah_modifier_group'],
                    d['jumlah_modifier'], d['deskripsi_item'], d['harga_sebelum_promo'],
                    d['harga_setelah_promo'], d['promo'], d['harga_flash_sale'],
                    d['promo_flash_sale'], d['stok_flash_sale'], d['ketersediaan'], d['link_foto']
                ])
                
            df_items = pd.DataFrame(item_data, columns=item_cols)
            
            mod_cols = [
                'Link outlet', 'Nama panjang', 'Nama pendek (ShopeeFood)', 'Store ID',
                'Nama item', 'Nama modifier group', 'Nama modifier', 'Tipe modifier',
                'Minimal', 'Maksimal', 'Harga modifier', 'Ketersediaan modifier'
            ]
            
            mod_data = []
            for m in modifier_rows:
                mod_data.append([
                    m['link_outlet'], m['nama_panjang'], m['nama_pendek'], m['store_id'],
                    m['nama_item'], m['nama_modifier_group'], m['nama_modifier'], m['tipe_modifier'],
                    m['minimal'], m['maksimal'], m['harga_modifier'], m['ketersediaan_modifier']
                ])
                
            df_mods = pd.DataFrame(mod_data, columns=mod_cols)
            
            # 9. Save Files
            os.makedirs(output_dir, exist_ok=True)
            
            def clean_name(s):
                cleaned = "".join(c for c in s if c.isalnum() or c in (' ', '_', '-')).rstrip()
                return cleaned.replace(' ', '_')
                
            safe_merchant = clean_name(nama_resto_actual)
            branch_raw = store_metadata.get('brand') or store_metadata.get('nama_resto_final') or store_metadata.get('nama_outlet') or ""
            safe_branch = clean_name(branch_raw)
            
            if safe_branch.lower() == safe_merchant.lower() or not safe_branch:
                combined_name = safe_merchant
            else:
                combined_name = f"{safe_merchant}_{safe_branch}"
                
            combined_name = re.sub(r'_+', '_', combined_name)
            
            items_csv_path = os.path.join(output_dir, f"grab_items_{combined_name}_{store_id}.csv")
            mods_csv_path = os.path.join(output_dir, f"grab_modifiers_{combined_name}_{store_id}.csv")
            excel_path = os.path.join(output_dir, f"grab_menu_{combined_name}_{store_id}.xlsx")
            
            df_items.to_csv(items_csv_path, index=False)
            df_mods.to_csv(mods_csv_path, index=False)
            
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                df_items.to_excel(writer, sheet_name='Items', index=False)
                df_mods.to_excel(writer, sheet_name='Modifiers', index=False)
                
            print(f"  [+] Ekstraksi menu berhasil. Data disimpan.")
            print(f"      - Item Count: {len(df_items)}")
            print(f"      - Modifier Count: {len(df_mods)}")
            
            return True, {
                'items_csv': items_csv_path,
                'mods_csv': mods_csv_path,
                'excel': excel_path,
                'items_count': len(df_items),
                'mods_count': len(df_mods)
            }
        except Exception as e:
            return False, f"Terjadi kesalahan saat meluncurkan browser: {e}"
        finally:
            try:
                browser.close()
            except:
                pass

