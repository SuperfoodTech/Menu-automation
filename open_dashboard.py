import sys
import os
import re
import json
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

# Add parent directory of menu_core to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from login_gofood import load_gofood_session, save_gofood_session

def select_email():
    try:
        from sheets import get_outlets_for_applicator
        outlets = get_outlets_for_applicator("gofood")
    except Exception as e:
        print(f"⚠️ Gagal mengambil daftar outlet dari Google Sheet / Cache: {e}")
        outlets = []
        
    email_to_outlets = {}
    for o in outlets:
        for em in o.get('emails', []):
            if em and '@' in em:
                email_to_outlets.setdefault(em.strip().lower(), []).append(o)
                
    # Sort emails alphabetically
    sorted_emails = sorted(list(email_to_outlets.keys()))
    
    print("\nSilakan pilih akun GoFood untuk dibuka:")
    for idx, em in enumerate(sorted_emails, 1):
        assoc_outlets = email_to_outlets[em]
        names = []
        for o in assoc_outlets[:3]: # Tampilkan max 3 outlet yang berasosiasi
            n = o.get('nama_resto_final') or o.get('nama_outlet') or 'Unknown'
            names.append(n)
        names_str = ", ".join(names)
        if len(assoc_outlets) > 3:
            names_str += "..."
        print(f"  [{idx}] {em} ({names_str})")
        
    print(f"  [99] Masukkan Email / Nomor Telepon Custom secara manual")
    print(f"  [q] Keluar")
    
    choice = input("\nPilihan (default 1): ").strip()
    if choice.lower() == 'q':
        sys.exit(0)
    if not choice:
        choice = '1'
        
    if choice == '99':
        custom = input("Masukkan email atau nomor handphone: ").strip()
        return custom
        
    try:
        c_idx = int(choice) - 1
        if 0 <= c_idx < len(sorted_emails):
            return sorted_emails[c_idx]
    except ValueError:
        pass
        
    print("⚠️ Pilihan tidak valid.")
    return None

def main():
    print("=" * 65)
    print("  🚀 GOFOOD INTERACTIVE DASHBOARD LAUNCHER")
    print("=" * 65)

    email = None
    while not email:
        email = select_email()

    print(f"\nTarget Account: {email}")
    print("=" * 65)

    # 1. Load session data
    session_data = load_gofood_session(email)
    
    # 2. Check proxy settings
    use_proxy = os.getenv("USE_PROXY", "false").lower() in ("true", "1", "yes")
    proxy_server = os.getenv("PROXY_SERVER")
    proxy_config = None
    if use_proxy and proxy_server:
        print(f"🔄 Menggunakan proxy: {proxy_server}")
        parsed = urlparse(proxy_server)
        if parsed.username and parsed.password:
            server_url = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port:
                server_url += f":{parsed.port}"
            proxy_config = {"server": server_url, "username": parsed.username, "password": parsed.password}
        else:
            proxy_config = {"server": proxy_server}

    # 3. Launch Playwright
    with sync_playwright() as p:
        print("[*] Launching browser (non-headless mode)...")
        browser = p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--no-sandbox'
            ]
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1366, 'height': 768},
            proxy=proxy_config
        )

        if session_data and session_data.get('cookies'):
            print("   🔑 Found active session! Loading cookies...")
            context.add_cookies(session_data['cookies'])
        else:
            print("   ⚠️ No active session found. You will need to login manually in the browser.")

        page = context.new_page()
        
        # Interceptor variables
        captured_menu = None
        captured_modifiers = []
        restaurant_uuid = None

        def handle_response(response):
            nonlocal captured_menu, restaurant_uuid
            # Intercept Menu API (Passive listening)
            if "gofood/merchant/v1/restaurants" in response.url and "/menus" in response.url:
                try:
                    if response.status == 200:
                        captured_menu = response.json()
                        match = re.search(r"restaurants/([^/]+)/menus", response.url)
                        if match:
                            restaurant_uuid = match.group(1)
                        print(f"\n   ✅ [Listener] Menu API Intercepted! Total categories: {len(captured_menu.get('menus', []))}")
                        
                        # Save automatically
                        store_id = None
                        parsed_url = urlparse(page.url)
                        query_params = parse_qs(parsed_url.query)
                        rest_id_param = query_params.get("restaurantId", [None])[0] or query_params.get("restaurant_id", [None])[0]
                        if rest_id_param:
                            store_id = f"G{rest_id_param}" if not rest_id_param.startswith("G") else rest_id_param
                        
                        api_dir = Path(__file__).parent / "gofood" / "docs" / "API"
                        api_dir.mkdir(parents=True, exist_ok=True)
                        
                        if store_id:
                            target_file = api_dir / f"menu-response-{store_id}.json"
                            with open(target_file, 'w', encoding='utf-8') as f:
                                json.dump(captured_menu, f, indent=4)
                            print(f"   💾 Saved menu to: {target_file}")
                except Exception as e:
                    pass

        page.on("response", handle_response)
        
        print("[*] Navigating to GoFood Merchant Portal...")
        page.goto("https://portal.gofoodmerchant.co.id/dashboard", wait_until="load")
        
        print("\n" + "="*60)
        print("  🟢 INTERACTIVE MODE IS ACTIVE")
        print("  - Please select the outlet manually in the browser.")
        print("  - Navigate to the GoFood Menu page.")
        print("  - Click 'Pengaturan GoFood' to open menu management.")
        print("  - Press [ENTER] in this terminal to FORCE CAPTURE the menu!")
        print("  - Type 'q' and press Enter to exit.")
        print("="*60 + "\n")

        # Keep browser open until closed by user
        try:
            while True:
                if page.is_closed():
                    print("[*] Browser window closed.")
                    break
                
                cmd = input("👉 Tekan [ENTER] untuk capture menu, atau ketik 'q' untuk keluar: ").strip()
                if cmd.lower() == 'q':
                    break
                
                print("[*] Mencoba mengekstrak data dari halaman...")
                # 1. Dapatkan Token
                token = page.evaluate("""() => {
                    const keys = ['token', 'access_token', 'accessToken', 'auth_token', 'authorization', 'gobiz-token', 'go-id-token'];
                    for (const k of keys) {
                        let val = localStorage.getItem(k) || sessionStorage.getItem(k);
                        if (val) {
                            if (val.startsWith('{')) {
                                try {
                                    const parsed = JSON.parse(val);
                                    val = parsed.token || parsed.access_token || parsed.accessToken || val;
                                } catch(e){}
                            }
                            if (val && val.length > 20) return val;
                        }
                    }
                    const tokenRegex = /[A-Za-z0-9-_=]+\\.[A-Za-z0-9-_=]+\\.?[A-Za-z0-9-_.+/=]*/;
                    for (let i = 0; i < localStorage.length; i++) {
                        const val = localStorage.getItem(localStorage.key(i));
                        if (val && val.length > 20) {
                            if (val.includes('eyJ')) return val;
                            const match = val.match(tokenRegex);
                            if (match) return match[0];
                        }
                    }
                    for (let i = 0; i < sessionStorage.length; i++) {
                        const val = sessionStorage.getItem(sessionStorage.key(i));
                        if (val && val.length > 20) {
                            if (val.includes('eyJ')) return val;
                            const match = val.match(tokenRegex);
                            if (match) return match[0];
                        }
                    }
                    return null;
                }""")

                if not token:
                    print("⚠️ Token otentikasi tidak ditemukan. Pastikan Anda sudah login di browser.")
                    continue

                if token.startswith("Bearer "):
                    token = token[7:]

                # 2. Dapatkan Restaurant UUID
                rest_uuid = page.evaluate("""() => {
                    const uuidRegex = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
                    for (let i = 0; i < localStorage.length; i++) {
                        const val = localStorage.getItem(localStorage.key(i));
                        const match = uuidRegex.exec(val);
                        if (match) return match[0];
                    }
                    for (let i = 0; i < sessionStorage.length; i++) {
                        const val = sessionStorage.getItem(sessionStorage.key(i));
                        const match = uuidRegex.exec(val);
                        if (match) return match[0];
                    }
                    const urlMatch = uuidRegex.exec(window.location.href);
                    if (urlMatch) return urlMatch[0];
                    return null;
                }""")

                # 3. Dapatkan Store ID (numeric)
                store_id = None
                parsed_url = urlparse(page.url)
                query_params = parse_qs(parsed_url.query)
                rest_id_param = query_params.get("restaurantId", [None])[0] or query_params.get("restaurant_id", [None])[0]
                if rest_id_param:
                    store_id = f"G{rest_id_param}" if not rest_id_param.startswith("G") else rest_id_param

                print(f"   ℹ️ Terdeteksi Token: {'Ya' if token else 'Tidak'}")
                print(f"   ℹ️ Terdeteksi Restaurant UUID: {rest_uuid}")
                print(f"   ℹ️ Terdeteksi Store ID: {store_id}")

                if not rest_uuid:
                    user_uuid = input("⚠️ UUID restaurant tidak terdeteksi. Masukkan UUID secara manual (atau Enter untuk melewati): ").strip()
                    if user_uuid:
                        rest_uuid = user_uuid
                    else:
                        print("❌ Gagal mendapatkan UUID restaurant. Tidak dapat memanggil API.")
                        continue

                # 4. Fetch data menu langsung dari halaman
                print(f"[*] Melakukan fetch menu langsung untuk UUID: {rest_uuid}...")
                captured_menu = page.evaluate("""async ({token, uuid}) => {
                    try {
                        const res = await fetch(`https://api.gojekapi.com/gofood/merchant/v1/restaurants/${uuid}/menus`, {
                            headers: {
                                "Authorization": "Bearer " + token,
                                "Authentication-Type": "go-id",
                                "Gojek-Country-Code": "ID",
                                "Accept": "application/json"
                            }
                        });
                        return await res.json();
                    } catch (e) {
                        return { error: e.message };
                    }
                }""", {"token": token, "uuid": rest_uuid})

                if not captured_menu or "error" in captured_menu or "menus" not in captured_menu:
                    print(f"❌ Gagal melakukan fetch menu: {captured_menu}")
                    continue

                print(f"   ✅ Berhasil menarik {len(captured_menu.get('menus', []))} kategori menu!")

                # 5. Fetch data modifier langsung dari halaman
                print(f"[*] Melakukan fetch variant categories...")
                captured_mods = page.evaluate("""async ({token, uuid}) => {
                    try {
                        const res = await fetch(`https://api.gojekapi.com/gofood/merchant/v1/restaurants/${uuid}/variant_categories`, {
                            headers: {
                                "Authorization": "Bearer " + token,
                                "Authentication-Type": "go-id",
                                "Gojek-Country-Code": "ID",
                                "Accept": "application/json"
                            }
                        });
                        const data = await res.json();
                        return data.variant_categories || [];
                    } catch (e) {
                        return [];
                    }
                }""", {"token": token, "uuid": rest_uuid})

                # 6. Minta input Store ID jika tidak terdeteksi di URL
                if not store_id:
                    user_store_id = input("👉 Masukkan Store ID outlet (contoh: G758360468): ").strip()
                    if user_store_id:
                        store_id = user_store_id if user_store_id.startswith("G") else f"G{user_store_id}"

                if not store_id:
                    store_id = "temp"

                # 7. Simpan File JSON
                api_dir = Path(__file__).parent / "gofood" / "docs" / "API"
                api_dir.mkdir(parents=True, exist_ok=True)

                menu_path = api_dir / f"menu-response-{store_id}.json"
                with open(menu_path, 'w', encoding='utf-8') as f:
                    json.dump(captured_menu, f, indent=4)
                print(f"   💾 Menu disimpan ke: {menu_path}")

                if captured_mods:
                    mod_path = api_dir / f"modifier-response-{store_id}.json"
                    with open(mod_path, 'w', encoding='utf-8') as f:
                        json.dump({"variant_categories": captured_mods}, f, indent=4)
                    print(f"   💾 Modifier disimpan ke: {mod_path}")
                
                print("\n🎉 CAPTURE BERHASIL SELESAI!")
                print("Anda dapat memproses outlet lain di browser, lalu tekan [ENTER] kembali untuk meng-capture.\n")

        except KeyboardInterrupt:
            print("\n[*] Interactive session stopped by user.")
        
        # Save session if logged in
        try:
            current_url = page.url
            if "/auth/login" not in current_url:
                cookies = context.cookies()
                local_storage = page.evaluate("() => ({...localStorage})")
                session_storage = page.evaluate("() => ({...sessionStorage})")
                access_token = local_storage.get("token") or local_storage.get("access_token")
                if not access_token:
                    access_token = session_storage.get("token") or session_storage.get("access_token")
                
                new_session = {
                    'timestamp': time.time(),
                    'access_token': access_token or (session_data.get('access_token') if session_data else None),
                    'cookies': cookies,
                    'localStorage': local_storage,
                    'sessionStorage': session_storage,
                }
                save_gofood_session(email, new_session)
                print(f"   💾 Saved updated session for {email}.")
        except Exception as e:
            print(f"   ⚠️ Failed to save updated session: {e}")

        try:
            browser.close()
        except:
            pass

if __name__ == "__main__":
    main()
