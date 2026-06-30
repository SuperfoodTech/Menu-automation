#!/usr/bin/env python3
import os
import re
import sys
import json
import time
import csv
import requests
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl
from dotenv import load_dotenv, set_key
from playwright.sync_api import sync_playwright

# Muat file .env dari folder menu
MENU_DIR = Path("/home/akbarhann/project/task-weekly/menu")
ENV_PATH = MENU_DIR / ".env"
load_dotenv(ENV_PATH)

# Master credential Google Sheet
MASTER_SHEET_URL = "https://docs.google.com/spreadsheets/d/14eCb8DAEXhmbYj9MFj2KzC7AhkulbCbSNPltN2m-go0/export?format=csv&gid=0"


def normalisasi_nomor_hp(nomor_hp):
    if not nomor_hp:
        return ""
    nomor_hp = str(nomor_hp).strip()
    if "@" in nomor_hp:
        return nomor_hp
    nomor_hp = re.sub(r'\D', '', nomor_hp)
    if nomor_hp.startswith("62"):
        return nomor_hp[2:]
    if nomor_hp.startswith("0"):
        return nomor_hp[1:]
    return nomor_hp


def fetch_gofood_outlets():
    """
    Mengambil semua outlet GoFood Live dari master Google Sheet.
    Mendeteksi kolom Email Login Go 1, Email Login Go 2, dan Nomor HP secara dinamis.
    """
    try:
        cache_buster_url = MASTER_SHEET_URL + f"&t={int(time.time())}"
        resp = requests.get(cache_buster_url, timeout=30)
        resp.raise_for_status()
        reader_rows = list(csv.reader(resp.text.splitlines()))
    except Exception as e:
        print(f"❌ Gagal mengambil Google Sheet master: {e}")
        return []

    if not reader_rows:
        return []

    header = [str(h).strip().lower() for h in reader_rows[0]]

    def col_idx(names):
        for n in names:
            for i, h in enumerate(header):
                if n in h:
                    return i
        return None

    idx_aplikasi = col_idx(['aplikasi'])
    idx_status   = col_idx(['status'])
    idx_outlet   = col_idx(['nama outlet'])
    idx_cabang   = col_idx(['cabang'])
    idx_store    = col_idx(['store id', 'store_id', 'merchant id'])
    
    # Cari kolom email secara dinamis
    idx_email1 = col_idx(['email login go 1'])
    if idx_email1 is None:
        idx_email1 = 24  # Fallback Kolom Y (0-indexed)
        
    idx_email2 = col_idx(['email login go 2'])
    if idx_email2 is None:
        idx_email2 = 25  # Fallback Kolom Z (0-indexed)

    # Cari nomor hp untuk Superfood secara dinamis (Nomor HP setelah akses superfood/login go 1)
    idx_phone = 27  # Default fallback ke index 27 (Kolom AB)
    idx_superfood = None
    for i, h in enumerate(header):
        if 'akses superfood' in h or 'login go 1' in h:
            idx_superfood = i
            break
    if idx_superfood is not None:
        for i in range(idx_superfood, len(header)):
            if 'nomor hp' in header[i]:
                idx_phone = i
                break

    outlets = []
    for row in reader_rows[1:]:
        if len(row) <= idx_phone:
            continue

        aplikasi = str(row[idx_aplikasi]).strip().lower() if idx_aplikasi is not None and len(row) > idx_aplikasi else ''
        status   = str(row[idx_status]).strip().lower()   if idx_status is not None and len(row) > idx_status else ''

        if 'gofood' not in aplikasi:
            continue
        if 'live' not in status:
            continue

        email1 = str(row[idx_email1]).strip() if len(row) > idx_email1 else ''
        email2 = str(row[idx_email2]).strip() if len(row) > idx_email2 else ''
        
        emails = []
        if email1 and email1 != "-":
            emails.append(email1)
        if email2 and email2 != "-" and email2 != email1:
            emails.append(email2)
            
        primary_email = emails[0] if emails else ""
        phone    = str(row[idx_phone]).strip() if len(row) > idx_phone else ''
        nama     = str(row[idx_outlet]).strip() if idx_outlet is not None and len(row) > idx_outlet else ''
        cabang   = str(row[idx_cabang]).strip() if idx_cabang is not None and len(row) > idx_cabang else ''
        store_id = str(row[idx_store]).strip()  if idx_store is not None  and len(row) > idx_store  else ''

        outlets.append({
            'nama_outlet': nama,
            'cabang'     : cabang,
            'email'      : primary_email,
            'emails'     : emails,
            'phone'      : phone,
            'store_id'   : store_id,
        })

    return outlets


def ambil_otp_dari_endpoint(url_dasar, action="getOtp", label_email=None):
    if not url_dasar:
        raise ValueError("URL endpoint OTP kosong.")

    if "docs.google.com/spreadsheets" in url_dasar:
        try:
            with urlopen(url_dasar, timeout=30) as response:
                content = response.read().decode("utf-8").strip()
                lines = content.splitlines()
                if not lines or len(lines) < 2:
                    return ""
                reader = csv.reader(lines)
                rows = list(reader)
                headers = [h.strip().lower() for h in rows[0]]
                
                otp_idx = -1
                for idx, h in enumerate(headers):
                    if "otp" in h:
                        otp_idx = idx
                        break
                
                if otp_idx == -1:
                    otp_idx = 1 if len(rows[0]) > 1 else 0
                    
                last_row = rows[-1]
                if len(last_row) > otp_idx:
                    return last_row[otp_idx].strip()
                return ""
        except Exception as e:
            print(f"⚠️ Gagal membaca OTP dari Sheets: {e}")
            return ""

    parsed = urlparse(url_dasar)
    query_params = dict(parse_qsl(parsed.query))
    query_params["action"] = action
    if label_email:
        query_params["label"] = label_email
    url_final = urlunparse(parsed._replace(query=urlencode(query_params)))

    with urlopen(url_final, timeout=30) as response:
        return response.read().decode("utf-8").strip()


def tunggu_otp_terbaru(url_dasar, action="getOtp", label_email=None, interval_detik=3, otp_awal_override=None, timeout_detik=15):
    """
    Menunggu OTP terbaru yang berbeda dari nilai awal agar tidak memakai OTP sebelumnya.
    otp_awal_override: Jika diisi, gunakan nilai ini sebagai baseline (snapshot sebelum OTP dikirim).
    """
    if otp_awal_override is not None:
        otp_awal = otp_awal_override
    else:
        try:
            otp_awal = ambil_otp_dari_endpoint(url_dasar, action=action, label_email=label_email)
        except Exception:
            otp_awal = ""
    
    batas_waktu = time.time() + timeout_detik
    print(f"   🤖 Menunggu OTP baru masuk ke inbox (maksimal {timeout_detik} detik)...")

    while time.time() < batas_waktu:
        time.sleep(interval_detik)
        try:
            otp_baru = ambil_otp_dari_endpoint(url_dasar, action=action, label_email=label_email)
            if otp_baru and otp_baru != otp_awal:
                return otp_baru
        except Exception:
            pass

    return otp_awal


def tutup_semua_popup(page):
    """
    Dismisses common popups, cookie consent banners, and onboarding overlays
    to prevent intercepting clicks on target elements.
    """
    print("   🤖 Mencoba mendeteksi dan menutup pop-up/cookie banner...")
    
    # 1. Cookie consent
    cookie_selectors = [
        'button:has-text("Terima Semua Cookie")',
        'button:has-text("Accept All Cookies")',
        'button:has-text("Terima")',
        'button:has-text("Accept")'
    ]
    for sel in cookie_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=1500)
                print(f"   ✅ Cookie banner ditutup ({sel})")
                time.sleep(0.5)
        except Exception:
            pass

    # 2. Tutorial / Lewati / Onboarding
    dismiss_selectors = [
        'button:has-text("Lewati")',
        'button:has-text("Lewati Tutorial")',
        'button:has-text("Selesai")',
        'button:has-text("Tutup")',
        'button:has-text("Nanti Saja")',
        '[aria-label="close"]',
        '[aria-label="Close"]',
        'button.close',
        '.dismiss-button',
        'button[class*="close"]',
        'button:has-text("×")',
        'button:has-text("✕")'
    ]
    for sel in dismiss_selectors:
        try:
            loc = page.locator(sel)
            for i in range(loc.count()):
                candidate = loc.nth(i)
                if candidate.is_visible():
                    candidate.click(timeout=1500)
                    print(f"   ✅ Pop-up/Tutorial ditutup ({sel})")
                    time.sleep(0.5)
        except Exception:
            pass


SESSION_FILE = MENU_DIR / "sessions" / "gofood_sessions.json"

def load_gofood_session(identifier):
    if not identifier:
        return None
    ident_str = str(identifier).strip().lower()
    if ident_str in ("", "-", "nan", "none", "null"):
        return None
    sanitized = re.sub(r'[^a-zA-Z0-9_.-]', '_', ident_str)
    json_file = MENU_DIR / "sessions" / f"session_gofood_{sanitized}.json"
    if not json_file.exists():
        phone_norm = normalisasi_nomor_hp(identifier)
        if phone_norm:
            json_file_old = MENU_DIR / f"session_{phone_norm}.json"
            if json_file_old.exists():
                json_file = json_file_old
    if not json_file.exists():
        return None
    try:
        with open(json_file, 'r') as f:
            return json.load(f)
    except Exception:
        return None

def save_gofood_session(identifier, session_data):
    if not identifier:
        return
    ident_str = str(identifier).strip().lower()
    if ident_str in ("", "-", "nan", "none", "null"):
        return
    sanitized = re.sub(r'[^a-zA-Z0-9_.-]', '_', ident_str)
    json_file = MENU_DIR / "sessions" / f"session_gofood_{sanitized}.json"
    try:
        os.makedirs(os.path.dirname(json_file), exist_ok=True)
        with open(json_file, 'w') as f:
            json.dump(session_data, f, indent=4)
        phone_norm = normalisasi_nomor_hp(identifier)
        if phone_norm and phone_norm != sanitized:
            json_file_old = MENU_DIR / f"session_{phone_norm}.json"
            with open(json_file_old, 'w') as f:
                json.dump(session_data, f, indent=4)
    except Exception as e:
        print(f"   ⚠️ Gagal menyimpan berkas sesi untuk {identifier}: {e}")


def login_outlet(outlet_info, proxy_config=None):
    """
    Membuka browser Chromium untuk login otomatis 1 outlet.
    Menangkap token, menyimpannya di .env, dan mengembalikannya.
    """
    nama = outlet_info['nama_outlet']
    cabang = outlet_info.get('cabang', '')
    emails_to_try = outlet_info.get('emails', [])
    if not emails_to_try:
        single_email = outlet_info.get('email', '')
        if single_email:
            emails_to_try = [single_email]
            
    phone = outlet_info.get('phone_raw', '') or outlet_info.get('phone', '')

    label = f"{nama} - {cabang}" if cabang and cabang != 'Tanpa Cabang' else nama

    print(f"\n🔄 Membuka browser untuk login otomatis ke: {label}")
    if emails_to_try:
        print(f"   📧 Emails: {', '.join(emails_to_try)}")
    if phone:
        print(f"   📱 Phone: {phone}")

    use_proxy = os.getenv("USE_PROXY", "false").lower() in ("true", "1", "yes")
    proxy_server = os.getenv("PROXY_SERVER")
    if proxy_config is None and use_proxy and proxy_server:
        parsed = urlparse(proxy_server)
        if parsed.username and parsed.password:
            server_url = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port:
                server_url += f":{parsed.port}"
            proxy_config = {"server": server_url, "username": parsed.username, "password": parsed.password}
        else:
            proxy_config = {"server": proxy_server}

    headless_mode = False
    try:
        env_headless = os.getenv("HEADLESS") or os.getenv("HEADLESS_GOFOOD")
        if env_headless is not None:
            headless_mode = env_headless.lower() in ("true", "1", "yes")
    except Exception:
        pass

    result = None

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless_mode,
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

        import random
        
        access_token = None
        session_loaded_successfully = False
        logged_in_email = None

        # Check if we have a cached session for one of the emails or phone
        cached_identifier = None
        cached_data = None
        for email in emails_to_try:
            cached_data = load_gofood_session(email)
            if cached_data:
                cached_identifier = email
                break
        if not cached_data and phone:
            cached_data = load_gofood_session(phone)
            if cached_data:
                cached_identifier = phone

        if cached_data and cached_data.get('cookies'):
            try:
                print(f"   🔑 Ditemukan sesi aktif untuk {cached_identifier}. Mencoba memuat sesi...")
                context.add_cookies(cached_data['cookies'])
                
                page = context.new_page()
                page.goto("https://portal.gofoodmerchant.co.id/dashboard", wait_until="load")
                time.sleep(2.0)
                
                # Check if we are logged in (i.e. URL does not contain /auth/login)
                current_url = page.url
                if "/auth/login" not in current_url:
                    print(f"   ✅ Sesi berhasil dimuat! Melewati login OTP untuk {cached_identifier}.")
                    access_token = cached_data.get('access_token')
                    session_loaded_successfully = True
                    logged_in_email = cached_identifier if "@" in str(cached_identifier) else None
                else:
                    print(f"   ⚠️ Sesi kedaluwarsa untuk {cached_identifier}. Melakukan login ulang...")
                    context.clear_cookies()
                    page.close()
            except Exception as e:
                print(f"   ⚠️ Gagal memuat sesi: {e}. Melakukan login ulang...")
                try:
                    context.clear_cookies()
                    page.close()
                except Exception:
                    pass

        if session_loaded_successfully:
            emails_to_try = []

        for email_idx, current_email in enumerate(emails_to_try):
            if access_token:
                break
                
            max_login_attempts = 2
            attempts_made = 0
            
            while attempts_made < max_login_attempts:
                attempt = attempts_made
                attempts_made += 1

                if access_token:
                    break
                    
                page = context.new_page()
                if current_email:
                    print(f"\n   ➡️ [Email: {current_email}] Membuka halaman login email langsung... (Percobaan {attempt + 1}/{max_login_attempts})")
                    page.goto("https://portal.gofoodmerchant.co.id/auth/login/email", wait_until="load")
                else:
                    print(f"\n   ➡️ Membuka halaman login... (Percobaan {attempt + 1}/{max_login_attempts})")
                    page.goto("https://portal.gofoodmerchant.co.id/auth/login", wait_until="load")

                time.sleep(1.0)
                
                otp_failed_timeout = False
                is_banned = False

                otp_endpoint = os.getenv("OTP_ENDPOINT_URL")
                label_email_cfg = os.getenv("GMAIL_OTP_LABEL", "OTP-GO")
                action_type = "getOtpEmail" if current_email else "getOtp"
                otp_snapshot_awal = ""

                # --- STEP 4: Ketik email secara human-like ---
                if current_email:
                    try:
                        email_input = page.wait_for_selector(
                            'input[type="email"], input[name="email"], input[placeholder*="email" i], input[placeholder*="Email" i], input[type="text"]',
                            timeout=15000
                        )
                        if email_input:
                            email_input.click()
                            time.sleep(0.3)
                            email_input.focus()
                            time.sleep(0.3)
                            for char in current_email:
                                email_input.type(char, delay=0)
                                time.sleep(random.uniform(0.05, 0.15))
                            time.sleep(0.5)

                            submit_btn = page.locator('button:has-text("Lanjut"), button:has-text("Submit"), button:has-text("Masuk"), button[type="submit"]')
                            if submit_btn.count() > 0:
                                submit_btn.first.click()
                            else:
                                email_input.press("Enter")
                            time.sleep(3)

                            # --- Pre-snapshot OTP sebelum tombol OTP diklik ---
                            if otp_endpoint:
                                try:
                                    otp_snapshot_awal = ambil_otp_dari_endpoint(otp_endpoint, action=action_type, label_email=label_email_cfg)
                                    print(f"   📸 Snapshot OTP awal: '{otp_snapshot_awal or '(kosong)'}' (sebelum OTP dikirim)")
                                except Exception:
                                    otp_snapshot_awal = ""

                            # Jika ada halaman pilihan login (password/OTP)
                            try:
                                btn_otp = page.locator('button:has-text("Masuk dengan OTP"), a:has-text("Masuk dengan OTP")').first
                                if btn_otp.count() > 0 and btn_otp.is_visible():
                                    btn_otp.click()
                                    print("   ✅ Tombol 'Masuk dengan OTP' diklik. OTP sedang dikirim...")
                                    time.sleep(2)
                            except Exception:
                                pass

                            # --- STEP 5: Automated OTP Polling & Fill ---
                            if otp_endpoint:
                                try:
                                    print("   🤖 Menunggu field OTP muncul...")
                                    otp_input_selector = 'input[autocomplete="one-time-code"], input[aria-label*="digit" i], div[class*="otp" i] input:not([type="checkbox"]):not([type="radio"]), input[name*="otp" i]:not([type="checkbox"]):not([type="radio"]), input[maxlength="1"]:not([type="checkbox"]):not([type="radio"])'
                                    
                                    otp_appeared = False
                                    start_wait_otp = time.time()
                                    while time.time() - start_wait_otp < 15:
                                        if page.locator(otp_input_selector).count() > 0 and page.locator(otp_input_selector).first.is_visible():
                                            otp_appeared = True
                                            break
                                        
                                        # Fast-fail deteksi Limit/Banned
                                        try:
                                            ban_msg1 = page.locator('text=/terlalu banyak/i')
                                            ban_msg2 = page.locator('text=/coba lagi/i')
                                            ban_msg3 = page.locator('text=/15 menit/i')
                                            if (ban_msg1.count() > 0 and ban_msg1.first.is_visible()) or \
                                               (ban_msg2.count() > 0 and ban_msg2.first.is_visible()) or \
                                               (ban_msg3.count() > 0 and ban_msg3.first.is_visible()):
                                                print("   ⚠️ Terdeteksi teks peringatan Limit/Banned. Membatalkan tunggu OTP...")
                                                break
                                        except Exception:
                                            pass
                                            
                                        time.sleep(1.0)
                                        
                                    if not otp_appeared:
                                        raise Exception("OTP Field timeout atau akun terindikasi banned")
                                        
                                    time.sleep(1)
                                except Exception as e:
                                    print(f"   ⚠️ {e}: Field OTP tidak muncul. Indikasi limit/banned 15 menit untuk email {current_email}. Menghentikan percobaan dan rotasi akun.")
                                    is_banned = True
                                    try:
                                        page.close()
                                    except Exception:
                                        pass
                                    break  # Keluar dari loop attempt, langsung rotasi ke email berikutnya

                                # 2. Lakukan polling dan input OTP
                                if not is_banned:
                                    try:
                                        print("   🤖 Polling OTP dari Gmail (snapshot awal sudah diambil sebelumnya)...")
                                        
                                        otp_code = tunggu_otp_terbaru(otp_endpoint, action=action_type, label_email=label_email_cfg, interval_detik=3, otp_awal_override=otp_snapshot_awal, timeout_detik=15)
                                        
                                        if otp_code and not (otp_code.isdigit() and len(otp_code) in (4, 6)):
                                            print(f"   ⚠️ OTP dari endpoint bukan format angka valid: {otp_code[:50]}...")
                                            otp_code = None
                                            
                                        if otp_code:
                                            print(f"   🤖 OTP didapat: {otp_code}. Memasukkan OTP...")
                                            otp_fields = page.locator(otp_input_selector).all()
                                            if len(otp_fields) > 0:
                                                otp_fields[0].focus()
                                                time.sleep(0.5)
                                                otp_fields[0].type(otp_code, delay=300)
                                                print("   ✅ OTP berhasil diisi otomatis.")
                                                
                                                time.sleep(1)
                                                submit_otp_btn = page.locator('button:has-text("Masuk"), button:has-text("Konfirmasi"), button:has-text("Verifikasi"), button:has-text("Lanjut"), button[type="submit"]')
                                                clicked = False
                                                for i in range(submit_otp_btn.count()):
                                                    btn = submit_otp_btn.nth(i)
                                                    if btn.is_visible() and btn.is_enabled():
                                                        print(f"   🤖 Mengklik tombol OTP: '{btn.text_content().strip()}'")
                                                        btn.click()
                                                        clicked = True
                                                        break
                                                if not clicked:
                                                    print("   🤖 Mengirim Enter sebagai fallback...")
                                                    page.keyboard.press("Enter")
                                                time.sleep(2)
                                        else:
                                            print("   ⚠️ Gagal mendapatkan OTP dalam 15 detik (atau format tidak valid).")
                                            otp_failed_timeout = True
                                    except Exception as e:
                                        print(f"   ⚠️ Gagal melakukan automasi OTP: {e}.")
                                        otp_failed_timeout = True
                            else:
                                print("   👉 Silakan isi kode OTP secara MANUAL di browser.")
                    except Exception as e:
                        print(f"   ⚠️ Gagal ketik email: {e}")

                if is_banned:
                    continue

                if otp_failed_timeout:
                    if attempt < max_login_attempts - 1:
                        print("   ⚠️ Menutup halaman dan menunggu 15 detik sebelum mengulang login (attempt ke-2)...")
                        try:
                            page.close()
                        except Exception:
                            pass
                        time.sleep(15)
                        continue
                    else:
                        print(f"   ⚠️ Melewati batas percobaan login untuk {current_email}. Rotasi ke email berikutnya/gagal.")
                        try:
                            page.close()
                        except Exception:
                            pass
                        continue

                # --- Tunggu access_token muncul di cookies (max 15 detik) ---
                attempt_token = None
                start_time = time.time()
                try:
                    while True:
                        if page.is_closed():
                            print("⚠️ Browser ditutup sebelum login selesai.")
                            break

                        cookies = context.cookies()
                        for cookie in cookies:
                            if cookie['name'] == 'access_token':
                                attempt_token = cookie['value']
                                break

                        if attempt_token:
                            access_token = attempt_token
                            logged_in_email = current_email
                            break

                        # Deteksi akun baru yang butuh verifikasi email
                        try:
                            error_msg1 = page.locator('text=/Email belum diverifikasi/i')
                            error_msg2 = page.locator('text=/silahkan login ulang/i')
                            if (error_msg1.count() > 0 and error_msg1.first.is_visible()) or \
                               (error_msg2.count() > 0 and error_msg2.first.is_visible()):
                                print("   ⚠️ Terdeteksi akun baru: 'Email belum diverifikasi'. Mempercepat percobaan ulang...")
                                max_login_attempts = 3
                                time.sleep(2.0)
                                break
                        except Exception:
                            pass

                        # Deteksi OTP Salah / Kadaluarsa
                        try:
                            otp_err1 = page.locator('text=/kode salah/i')
                            otp_err2 = page.locator('text=/tidak valid/i')
                            otp_err3 = page.locator('text=/kadaluarsa/i')
                            if (otp_err1.count() > 0 and otp_err1.first.is_visible()) or \
                               (otp_err2.count() > 0 and otp_err2.first.is_visible()) or \
                               (otp_err3.count() > 0 and otp_err3.first.is_visible()):
                                print("   ⚠️ Terdeteksi pesan 'OTP Salah/Tidak Valid'. Mempercepat percobaan ulang...")
                                break
                        except Exception:
                            pass

                        # Deteksi Ban 15 Menit setelah submit OTP
                        try:
                            ban_err1 = page.locator('text=/terlalu banyak/i')
                            ban_err2 = page.locator('text=/coba lagi/i')
                            ban_err3 = page.locator('text=/15 menit/i')
                            if (ban_err1.count() > 0 and ban_err1.first.is_visible()) or \
                               (ban_err2.count() > 0 and ban_err2.first.is_visible()) or \
                               (ban_err3.count() > 0 and ban_err3.first.is_visible()):
                                print("   ⚠️ Terdeteksi teks Limit/Banned. Membatalkan tunggu token...")
                                is_banned = True
                                break
                        except Exception:
                            pass

                        time.sleep(1.0)

                        if time.time() - start_time > 5:
                            try:
                                if "/auth/login" in page.url:
                                    print("   ⚠️ (Fallback) Timeout 5 detik: URL masih stuck di halaman login. Mempercepat percobaan ulang...")
                                    max_login_attempts = 3
                                    break
                            except Exception:
                                pass

                        if time.time() - start_time > 15:
                            print("⚠️ Timeout 15 detik menunggu access_token.")
                            break

                except KeyboardInterrupt:
                    print("\n⚠️ Dibatalkan oleh pengguna.")
                    break
                except Exception as e:
                    print(f"❌ Error: {e}")

                if not access_token:
                    try:
                        page.close()
                    except Exception:
                        pass

                    if is_banned:
                        print(f"   ⚠️ Akun {current_email} terindikasi Limit/Banned. Langsung rotasi ke email berikutnya.")
                        break

                    if attempt < max_login_attempts - 1:
                        print(f"   ⚠️ Token tidak ditemukan. Kembali ke login page dengan email yang sama ({current_email})...")
                        continue
                    else:
                        print(f"   ⚠️ Token tidak ditemukan setelah {max_login_attempts} percobaan untuk {current_email}. Rotasi ke email berikutnya...")

        if access_token:
            print(f"🎉 LOGIN SUKSES untuk {label}!")

            # --- HANDLE CHOOSE OUTLET / BRAND PAGE (IF APPLICABLE) ---
            print("   🤖 Memeriksa apakah berada di halaman pemilihan outlet/merchant...")
            try:
                # Tunggu URL berubah ke salah satu halaman utama (dashboard, analytics, choose, outlet)
                page.wait_for_url(re.compile(r".*(dashboard|analytics|choose|outlet).*"), timeout=15000)
            except Exception:
                pass

            current_url = page.url
            print(f"   🤖 URL saat ini setelah login: {current_url}")
            
            # Jika URL mengandung 'choose' atau 'choose-outlet', kita perlu memilih merchant
            if "choose" in current_url or "outlet" in current_url:
                tutup_semua_popup(page)
                search_name = outlet_info.get('nama_resto_final') or outlet_info.get('nama_outlet') or ''
                brand_name = outlet_info.get('brand') or ''
                
                print(f"   🤖 Halaman pemilihan terdeteksi. Mencari cabang: {search_name or brand_name}...")
                
                chosen = False
                # Coba beberapa nama pencarian
                candidates = [search_name, brand_name]
                if search_name:
                    candidates.append(search_name.replace(',', ''))
                    words = [w.strip() for w in search_name.replace(',', ' ').split() if len(w.strip()) > 2]
                    common_words = {'rm', 'depot', 'warung', 'sate', 'resto', 'restaurant', 'kuliner', 'kedai'}
                    filtered_words = [w for w in words if w.lower() not in common_words]
                    if filtered_words:
                        candidates.append(" ".join(filtered_words[:2]))
                
                for candidate in candidates:
                    if not candidate or candidate.lower() == 'nan':
                        continue
                    try:
                        print(f"   🤖 Mencoba mencari element dengan teks: '{candidate}'")
                        outlet_element = page.locator(f"text={candidate}").first
                        if outlet_element.count() > 0 and outlet_element.is_visible():
                            outlet_element.click(force=True)
                            print(f"   ✅ Berhasil memilih cabang dengan teks '{candidate}'")
                            chosen = True
                            break
                    except Exception:
                        continue
                
                if not chosen:
                    print("   ⚠️ Cabang target tidak ditemukan di halaman pemilihan, mencoba mengklik element pertama yang tersedia...")
                    try:
                        first_card = page.locator('[class*="card" i], [class*="item" i], a, button').filter(has_text=re.compile(r".+")).first
                        if first_card.count() > 0:
                            first_card.click(force=True)
                            print("   ✅ Mengklik element/kartu pertama sebagai fallback.")
                    except Exception as e:
                        print(f"   ⚠️ Gagal melakukan fallback pemilihan cabang: {e}")
            
            # Tunggu hingga halaman beralih ke dashboard/analytics
            try:
                page.wait_for_url(re.compile(r".*(dashboard|analytics|gofood).*"), timeout=20000)
                print(f"   🤖 Masuk ke halaman utama: {page.url}")
            except Exception:
                print("   ⚠️ Timeout menunggu pengalihan ke dashboard/halaman utama.")

            # --- REDIRECT TO MENUS PAGE AND INTERCEPT API ---
            store_id = outlet_info.get('store_id', '')
            captured_menu = None
            captured_modifiers = []
            if store_id:
                store_id_clean = str(store_id).strip()
                print(f"   🤖 Target Store ID: {store_id_clean}")
                try:
                    # Register response listener to capture API response asynchronously
                    def handle_response(response):
                        nonlocal captured_menu
                        if "gofood/merchant/v1/restaurants" in response.url and "/menus" in response.url:
                            try:
                                if response.status == 200:
                                    captured_menu = response.json()
                                    print(f"   ✅ [Listener] Berhasil menangkap response API Menu! Total kategori: {len(captured_menu.get('menus', []))}")
                            except Exception as e:
                                print(f"   ⚠️ [Listener] Gagal memproses JSON response: {e}")
                                
                        if "variant_categories" in response.url:
                            try:
                                if response.status == 200:
                                    data = response.json()
                                    cats = data.get("variant_categories", [])
                                    if cats:
                                        captured_modifiers.extend(cats)
                                        print(f"   ✅ [Listener] Berhasil menangkap {len(cats)} modifier category dari API!")
                            except Exception as e:
                                print(f"   ⚠️ [Listener] Gagal memproses JSON modifier response: {e}")
                    
                    page.on("response", handle_response)
                    
                    # 1. Coba klik Menu tab di sidebar dengan selector href yang presisi
                    print("   🤖 Mengklik tab Menu di sidebar...")
                    tutup_semua_popup(page)
                    menu_clicked = False
                    sidebar_locators = [
                        'a[href="/gofood"]',
                        'a[href*="/gofood"]',
                        "aside a:has-text('Menu')",
                        "nav a:has-text('Menu')",
                        "a:has-text('Menu')",
                        "text=Menu"
                    ]
                    for sel in sidebar_locators:
                        try:
                            loc = page.locator(sel)
                            for i in range(loc.count()):
                                candidate = loc.nth(i)
                                if candidate.is_visible():
                                    candidate.click(force=True)
                                    menu_clicked = True
                                    break
                            if menu_clicked:
                                break
                        except Exception:
                            continue
                            
                    if not menu_clicked:
                        print("   🤖 Tab Menu tidak ditemukan di sidebar, mencoba navigasi langsung...")
                        page.goto("https://portal.gofoodmerchant.co.id/gofood", wait_until="domcontentloaded")
                    else:
                        try:
                            page.wait_for_url("**/gofood**", timeout=8000)
                        except Exception:
                            # Fallback jika click tidak memicu perpindahan URL
                            page.goto("https://portal.gofoodmerchant.co.id/gofood", wait_until="domcontentloaded")
                    
                    # Cek apakah sudah otomatis ter-redirect ke halaman menu items (untuk single-branch)
                    current_url = page.url
                    if "/menu-items" in current_url:
                        print("   🤖 Halaman otomatis beralih ke Menu Items (Single Branch). Menunggu capture...")
                    else:
                        # 2. Kita berada di halaman list cabang, cari baris outlet target
                        print("   🤖 Menunggu daftar cabang/outlet dimuat...")
                        try:
                            page.wait_for_selector("tr, button:has-text('Pengaturan GoFood')", timeout=10000)
                        except Exception:
                            pass
                        
                        digits_only = "".join(c for c in store_id_clean if c.isdigit())
                        row_loc = None
                        
                        # A. Cari berdasarkan angka ID (karena prefix M/G bisa berbeda di sheet vs portal)
                        if digits_only:
                            tr_loc = page.locator(f"tr:has-text('{digits_only}')")
                            if tr_loc.count() > 0:
                                row_loc = tr_loc.first
                                print(f"   🤖 Menemukan baris berdasarkan ID angka: {digits_only}")
                        
                        # B. Cari berdasarkan nama outlet jika belum ketemu
                        search_name = outlet_info.get('nama_resto_final') or outlet_info.get('nama_outlet') or ''
                        if not row_loc and search_name and search_name.lower() != 'nan':
                            words = [w.strip() for w in search_name.replace(',', ' ').split() if len(w.strip()) > 2]
                            common_words = {'rm', 'depot', 'warung', 'sate', 'resto', 'restaurant', 'kuliner', 'kedai'}
                            filtered_words = [w for w in words if w.lower() not in common_words]
                            search_keyword = ""
                            if filtered_words:
                                search_keyword = filtered_words[0]
                            elif words:
                                search_keyword = words[0]
                                
                            if search_keyword:
                                tr_loc = page.locator(f"tr:has-text('{search_keyword}')")
                                if tr_loc.count() > 0:
                                    row_loc = tr_loc.first
                                    print(f"   🤖 Menemukan baris berdasarkan kata nama outlet: {search_keyword}")
                                        
                        # C. Jika hanya ada 1 baris data di tabel (selain header), pilih otomatis
                        if not row_loc:
                            rows = page.locator("tr")
                            if rows.count() == 2:  # header + 1 data row
                                row_loc = rows.nth(1)
                                print("   🤖 Hanya ada satu outlet di tabel, memilih otomatis...")
                                
                        # D. Jika masih tidak ketemu, gunakan search input field dengan kata kunci nama yang dibersihkan
                        if not row_loc:
                            search_input = page.locator("input[placeholder*='Cari nama' i], input[placeholder*='Cari' i]").first
                            if search_input.count() > 0 and search_input.is_visible():
                                # Buat kata kunci pencarian yang bersih
                                search_keyword = ""
                                if search_name and search_name.lower() != 'nan':
                                    words = [w.strip() for w in search_name.replace(',', ' ').split() if len(w.strip()) > 2]
                                    common_words = {'rm', 'depot', 'warung', 'sate', 'resto', 'restaurant', 'kuliner', 'kedai'}
                                    filtered_words = [w for w in words if w.lower() not in common_words]
                                    if filtered_words:
                                        search_keyword = " ".join(filtered_words[:2])
                                    elif words:
                                        search_keyword = " ".join(words[:2])
                                if not search_keyword:
                                    search_keyword = digits_only
                                    
                                print(f"   🤖 Mencari outlet di search bar menggunakan kata kunci: {search_keyword}")
                                search_input.fill(search_keyword)
                                time.sleep(0.5)
                                page.keyboard.press("Enter")
                                cari_btn = page.locator("button:has-text('Cari')").first
                                if cari_btn.count() > 0 and cari_btn.is_visible():
                                    cari_btn.click()
                                time.sleep(3)
                                
                                # Cek ulang hasil pencarian
                                if digits_only:
                                    tr_loc = page.locator(f"tr:has-text('{digits_only}')")
                                    if tr_loc.count() > 0:
                                        row_loc = tr_loc.first
                                if not row_loc and search_keyword:
                                    tr_loc = page.locator(f"tr:has-text('{search_keyword.split()[0]}')")
                                    if tr_loc.count() > 0:
                                        row_loc = tr_loc.first
                                if not row_loc:
                                    rows = page.locator("tr")
                                    if rows.count() == 2:
                                        row_loc = rows.nth(1)
                                        
                        # E. Klik tombol Pengaturan GoFood
                        tutup_semua_popup(page)
                        if row_loc:
                            button_locator = row_loc.locator("button:has-text('Pengaturan GoFood'), a:has-text('Pengaturan GoFood')").first
                        else:
                            button_locator = page.locator("button:has-text('Pengaturan GoFood'), a:has-text('Pengaturan GoFood')").first
                            
                        if button_locator.count() > 0 and button_locator.is_visible():
                            print("   🤖 Mengklik tombol 'Pengaturan GoFood'...")
                            button_locator.click(force=True)
                        else:
                            print("   ⚠️ Tombol 'Pengaturan GoFood' tidak ditemukan/tidak dapat diklik.")
                            
                    # Tunggu hingga captured_menu terisi
                    print("   🤖 Menunggu response API Menu ditangkap...")
                    start_wait = time.time()
                    while captured_menu is None and (time.time() - start_wait) < 20:
                        page.wait_for_timeout(500)
                        
                    # Beri waktu tambahan 5 detik untuk menangkap pemanggilan API variant_categories
                    if captured_menu is not None:
                        print("   🤖 Menu ditangkap, menunggu 5 detik tambahan untuk mengintersepsi semua modifier...")
                        page.wait_for_timeout(5000)
                        
                        # Dapatkan restaurant_id dari captured_menu untuk fetch langsung v1 variant categories
                        restaurant_id = None
                        menus_list = captured_menu.get("menus", [])
                        for menu_cat in menus_list:
                            items_list = menu_cat.get("menu_items", [])
                            for m_item in items_list:
                                if m_item.get("restaurant_id"):
                                    restaurant_id = m_item.get("restaurant_id")
                                    break
                            if restaurant_id:
                                break
                        
                        if restaurant_id and access_token:
                            print(f"   🤖 [Direct Fetch] Mencoba fetch langsung v1 variant categories untuk restaurant: {restaurant_id}...")
                            try:
                                direct_cats = page.evaluate("""async ({token, rest_id}) => {
                                    try {
                                        const res = await fetch(`https://api.gojekapi.com/gofood/merchant/v1/restaurants/${rest_id}/variant_categories`, {
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
                                }""", {"token": access_token, "rest_id": restaurant_id})
                                
                                if direct_cats:
                                    captured_modifiers.extend(direct_cats)
                                    print(f"   ✅ [Direct Fetch] Berhasil mendapatkan {len(direct_cats)} variant categories langsung dari API v1!")
                            except Exception as e:
                                print(f"   ⚠️ [Direct Fetch] Gagal fetch langsung variant categories: {e}")
                        
                    # Hapus listener agar tidak berpotensi memory leak
                    try:
                        page.remove_listener("response", handle_response)
                    except Exception:
                        pass
                        
                except Exception as e:
                    print(f"   ⚠️ Gagal menangkap response API Menu: {e}")

            # Fetch user profile
            user_data = None
            try:
                user_data = page.evaluate("""async (token) => {
                    try {
                        const res = await fetch("https://api.gobiz.co.id/v1/users/me", {
                            headers: {
                                "Authorization": "Bearer " + token,
                                "Authentication-Type": "go-id"
                            }
                        });
                        return await res.json();
                    } catch (e) { return null; }
                }""", access_token)
            except Exception:
                pass

            all_cookies = context.cookies()
            local_storage = {}
            session_storage = {}
            try:
                local_storage = page.evaluate("() => ({...localStorage})")
                session_storage = page.evaluate("() => ({...sessionStorage})")
            except Exception:
                pass

            # Deduplicate captured modifiers (prioritize those with 'id' or 'master_variant_category_id')
            deduped_modifiers = []
            seen_ids = set()
            
            def get_priority(m):
                return 0 if (m.get("id") or m.get("master_variant_category_id")) else 1
                
            sorted_modifiers = sorted(captured_modifiers, key=get_priority)
            
            for m in sorted_modifiers:
                cid = m.get("common_id") or m.get("master_variant_category_id")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    deduped_modifiers.append(m)

            result = {
                'access_token': access_token,
                'user_data': user_data,
                'cookies': all_cookies,
                'localStorage': local_storage,
                'sessionStorage': session_storage,
                'captured_menu': captured_menu,
                'captured_modifiers': deduped_modifiers,
            }

            # Save session for future runs
            if not session_loaded_successfully:
                session_data = {
                    'timestamp': time.time(),
                    'access_token': access_token,
                    'cookies': all_cookies,
                    'localStorage': local_storage,
                    'sessionStorage': session_storage,
                }
                if logged_in_email:
                    save_gofood_session(logged_in_email, session_data)
                elif emails_to_try:
                    for email in emails_to_try:
                        save_gofood_session(email, session_data)
                if phone:
                    save_gofood_session(phone, session_data)
        else:
            print(f"❌ Gagal mendapatkan token untuk {label}.")

        try:
            browser.close()
        except Exception:
            pass

        return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="GoFood Multi-Outlet Manual Login (Menu Extractor Version)")
    parser.add_argument("--no-proxy", action="store_true", help="Nonaktifkan proxy/WARP")
    args_cli = parser.parse_args()

    print("=" * 60)
    print("  🔑 GOFOOD LOGIN UTILITY (NEW COLUMNS GID=0)  ")
    print("=" * 60)

    # Proxy config
    use_proxy = os.getenv("USE_PROXY", "false").lower() in ("true", "1", "yes")
    proxy_server = os.getenv("PROXY_SERVER")

    if args_cli.no_proxy:
        use_proxy = False
        print("🚫 Proxy dinonaktifkan.")

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

    # Ambil daftar outlet dari Google Sheet
    print("\n📋 Mengambil daftar outlet GoFood dari Google Sheet...")
    outlets = fetch_gofood_outlets()

    # Filter hanya yang punya email (Email Login Go 1 atau Email Login Go 2 tidak kosong)
    outlets_with_email = [o for o in outlets if o.get('emails') and any('@' in em for em in o['emails'])]

    if not outlets_with_email:
        print("❌ Tidak ada outlet GoFood dengan email kredensial yang tersedia.")
        return

    # Cek token yang sudah ada di .env
    existing_tokens = {}
    for key, value in os.environ.items():
        if key.startswith('BEARER_TOKEN_') and value:
            suffix = key[len('BEARER_TOKEN_'):]
            phone_part = suffix.split('_')[0]
            phone_norm = normalisation_nomor_hp(phone_part)
            if phone_norm:
                existing_tokens[phone_norm] = True

    # Tampilkan daftar
    print(f"\n📋 Ditemukan {len(outlets_with_email)} outlet GoFood Live dengan email:\n")
    for i, o in enumerate(outlets_with_email, 1):
        phone_norm = normalisation_nomor_hp(o['phone'])
        has_token = "✅ Sudah Login" if phone_norm in existing_tokens else "❌ Belum Login"
        cabang_str = f" - {o['cabang']}" if o['cabang'] else ""
        store_str = f" (Store: {o['store_id']})" if o['store_id'] else ""
        print(f"  [{i:2d}] {o['nama_outlet']}{cabang_str}{store_str}")
        emails_str = ", ".join(o.get('emails', [])) if o.get('emails') else o['email']
        print(f"       📧 {emails_str}  |  {has_token}")

    print(f"\n  Pilih outlet untuk login (contoh: 1,3,5 atau 'all' or 'new'):")
    pilihan = input("  Masukkan pilihan: ").strip().lower()

    selected = []
    if pilihan == 'all':
        selected = list(range(len(outlets_with_email)))
    elif pilihan == 'new':
        for idx, o in enumerate(outlets_with_email):
            phone_norm = normalisation_nomor_hp(o['phone'])
            if phone_norm not in existing_tokens:
                selected.append(idx)
    else:
        # Parsir comma separated indices
        parts = pilihan.split(',')
        for p in parts:
            p = p.strip()
            if '-' in p:
                start_s, end_s = p.split('-')
                start = int(start_s.strip()) - 1
                end = int(end_s.strip()) - 1
                selected.extend(range(start, end + 1))
            elif p.isdigit():
                idx = int(p) - 1
                if 0 <= idx < len(outlets_with_email):
                    selected.append(idx)

    # Filter unique & sorted
    selected = sorted(list(set(selected)))

    if not selected:
        print("❌ Tidak ada outlet terpilih yang valid.")
        return

    print(f"\n🚀 Memulai login manual untuk {len(selected)} outlet...")

    success_count = 0
    for seq, idx in enumerate(selected, 1):
        outlet = outlets_with_email[idx]
        print(f"\n[{seq}/{len(selected)}] ", end="")

        result = login_outlet(outlet, proxy_config)

        if result and result.get('access_token'):
            token = result['access_token']
            phone_norm = normalisation_nomor_hp(outlet['phone'])
            sanitized_name = re.sub(r'[^a-zA-Z0-9]', '', outlet['nama_outlet'])
            suffix = f"_{phone_norm}_{sanitized_name}"

            # Simpan ke .env di core folder
            try:
                set_key(str(ENV_PATH), "BEARER_TOKEN", token)
                set_key(str(ENV_PATH), f"BEARER_TOKEN{suffix}", token)
                set_key(str(ENV_PATH), "ACTIVE_NOMOR_HP", phone_norm)
                set_key(str(ENV_PATH), f"NAMA_OUTLET{suffix}", outlet['nama_outlet'])
                if outlet['cabang']:
                    set_key(str(ENV_PATH), f"CABANG{suffix}", outlet['cabang'])
                if outlet['store_id']:
                    set_key(str(ENV_PATH), f"STORE_ID{suffix}", outlet['store_id'])

                print(f"   ✅ Token disimpan: BEARER_TOKEN{suffix}")
                success_count += 1
            except Exception as e:
                print(f"   ❌ Gagal simpan ke .env: {e}")
                print(f"   Token: {token[:50]}...")

            # Dump session JSON ke menu folder
            try:
                dump = {
                    'timestamp': time.time(),
                    'outlet': outlet,
                    'user': result.get('user_data'),
                    'cookies': result.get('cookies', []),
                    'localStorage': result.get('localStorage', {}),
                    'sessionStorage': result.get('sessionStorage', {}),
                }
                json_file = MENU_DIR / f"session_{phone_norm}.json"
                with open(json_file, 'w') as f:
                    json.dump(dump, f, indent=4)
                print(f"   💾 Session dump: session_{phone_norm}.json")
            except Exception as e:
                print(f"   ❌ Gagal menyimpan berkas sesi: {e}")

            # Simpan captured menu response jika ada
            if result.get('captured_menu'):
                try:
                    api_dir = MENU_DIR / "gofood" / "docs" / "API"
                    api_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Simpan file spesifik store id
                    store_id = outlet.get('store_id', '')
                    if store_id:
                        menu_file_specific = api_dir / f"menu-response-{store_id}.json"
                        with open(menu_file_specific, 'w', encoding='utf-8') as f:
                            json.dump(result['captured_menu'], f, indent=4)
                        print(f"   💾 Menu response spesifik disimpan ke: menu/gofood/docs/API/menu-response-{store_id}.json")
                    
                    # Simpan ke default menu-response.json
                    menu_file = api_dir / "menu-response.json"
                    with open(menu_file, 'w', encoding='utf-8') as f:
                        json.dump(result['captured_menu'], f, indent=4)
                    print(f"   💾 Menu response default disimpan ke: menu/gofood/docs/API/menu-response.json")
                    
                    # Simpan captured modifier response jika ada
                    if result.get('captured_modifiers'):
                        mod_file_specific = api_dir / f"modifier-response-{store_id}.json"
                        with open(mod_file_specific, 'w', encoding='utf-8') as f:
                            json.dump({"variant_categories": result['captured_modifiers']}, f, indent=4)
                        print(f"   💾 Modifier response spesifik disimpan ke: menu/gofood/docs/API/modifier-response-{store_id}.json")
                        
                        # Simpan ke default modifier-response.json
                        mod_file = api_dir / "modifier-response.json"
                        with open(mod_file, 'w', encoding='utf-8') as f:
                            json.dump({"variant_categories": result['captured_modifiers']}, f, indent=4)
                        print(f"   💾 Modifier response default disimpan ke: menu/gofood/docs/API/modifier-response.json")
                except Exception as e:
                    print(f"   ❌ Gagal menyimpan menu-response.json / modifier-response.json: {e}")

        if seq < len(selected):
            print(f"\n   ⏳ Lanjut ke outlet berikutnya dalam 2 detik...")
            time.sleep(2)

    print(f"\n{'='*60}")
    print(f"  ✅ SELESAI: {success_count}/{len(selected)} outlet berhasil login.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
