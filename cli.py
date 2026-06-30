#!/usr/bin/env python3
"""
=================================================================
  SUPERFOOD TECH — Unified Menu & Modifier Extractor Pipeline
  Interactive CLI for Shopee, Grab & GoFood
=================================================================
"""

import os
import sys
import time
import re
from datetime import datetime

# Add parent directory of menu_core to sys.path so imports work
MENU_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, MENU_DIR)

def get_output_dir(applicator, clean_outlet):
    return os.path.join(MENU_DIR, applicator, "outlets", clean_outlet)

from sheets import get_outlets_for_applicator
from shopee.core.pull import extract_shopee_menu
from grab.core.pull import extract_grab_menu
from gofood.core.pull import extract_gofood_menu
from shopee.core.client import ShopeeModifyClient
from shopee.core.create import add_menu_shopee
from shopee.core.edit import edit_menu_shopee, _boot_client as _shopee_boot_client
from shopee.core.pull import list_menu_shopee

RESET   = "\033[0m"
BOLD    = "\033[1m"
GREEN   = "\033[92m"
CYAN    = "\033[96m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
MAGENTA = "\033[95m"
DIM     = "\033[2m"

def banner():
    print(f"\033[90m=================================================================\033[0m")
    print(f"  {BOLD}{CYAN}      SUPERFOOD TECH — MENU & MODIFIER EXTRACTOR PIPELINE{RESET}")
    print(f"\033[90m=================================================================\033[0m")
    print()

import json

def interactive_menu():
    state = "applicator"
    applicator = None
    outlets = []
    selected_outlet = None
    
    while True:
        if state == "applicator":
            os.system('cls' if os.name == 'nt' else 'clear')
            banner()
            print(f"  {BOLD}Pilih Aplikator/Platform:{RESET}")
            print(f"    {MAGENTA}[1]{RESET} ShopeeFood")
            print(f"    {GREEN}[2]{RESET} GrabFood")
            print(f"    {CYAN}[3]{RESET} GoFood")
            print(f"    {YELLOW}[4]{RESET} Keluar")
            print(f"    {CYAN}[5]{RESET} {BOLD}Kelola Menu ShopeeFood (Add / Edit){RESET}")
            print()
            
            choice = input(f"  {BOLD}Pilihan (1/2/3/4/5):{RESET} ").strip()
            if choice == "4":
                print("  Keluar.")
                sys.exit(0)
            elif choice == "1":
                applicator = "shopee"
                state = "load_outlets"
            elif choice == "2":
                applicator = "grab"
                state = "load_outlets"
            elif choice == "3":
                applicator = "gofood"
                state = "load_outlets"
            elif choice == "5":
                menu_manager_shopee()
                # kembali ke pilihan utama setelah selesai
            else:
                print(f"  {RED}Pilihan tidak valid.{RESET}")
                time.sleep(1)
                
        elif state == "load_outlets":
            print(f"\n  [*] Mengunduh & memuat daftar outlet untuk {applicator.upper()}...")
            try:
                outlets = get_outlets_for_applicator(applicator)
                if not outlets:
                    print(f"  {RED}[ERROR] Tidak ada outlet live yang ditemukan untuk {applicator.upper()}.{RESET}")
                    time.sleep(2)
                    state = "applicator"
                else:
                    state = "select_outlet"
            except Exception as e:
                print(f"  {RED}[ERROR] Gagal memuat daftar outlet: {e}{RESET}")
                time.sleep(3)
                state = "applicator"
                
        elif state == "select_outlet":
            os.system('cls' if os.name == 'nt' else 'clear')
            banner()
            
            # Get unique Nama Outlet (nama_outlet) values
            unique_outlets = sorted(list(set(o['nama_outlet'] for o in outlets if o['nama_outlet'])))
            
            print(f"  {BOLD}Pilih Nama Outlet {applicator.upper()}:{RESET}")
            print(f"    {GREEN}[all]{RESET} Jalankan semua outlet dan cabang")
            print(f"    {GREEN}[new]{RESET} Jalankan HANYA outlet/cabang yang belum ditarik")
            for idx, name in enumerate(unique_outlets):
                print(f"    {GREEN}[{idx + 1:3d}]{RESET} {name}")
                
            print(f"    {YELLOW}[b  ]{RESET} Kembali ke pemilihan aplikator")
            print()
            
            choice = input(f"  {BOLD}Pilih nomor outlet (atau 'all'/'new'/'b'):{RESET} ").strip()
            if choice.lower() == 'b':
                state = "applicator"
            elif choice.lower() == 'all':
                selected_outlet = outlets
                state = "confirm_all"
            elif choice.lower() == 'new':
                # Filter outlets to keep only those that have not been run
                filtered_outlets = []
                for o in outlets:
                    raw_outlet = o.get('nama_outlet') or o.get('nama_resto_final') or o.get('merchant_name') or 'unknown'
                    clean_outlet = "".join(c for c in raw_outlet if c.isalnum() or c in (' ', '_', '-')).strip()
                    clean_outlet = re.sub(r'\s+', ' ', clean_outlet).lower()
                    
                    output_dir = get_output_dir(applicator, clean_outlet)
                    
                    is_processed = False
                    if os.path.exists(output_dir):
                        files = os.listdir(output_dir)
                        has_files = any(f.endswith('.csv') or f.endswith('.xlsx') for f in files)
                        if len(files) > 0 and has_files:
                            is_processed = True
                            
                    if not is_processed:
                        filtered_outlets.append(o)
                
                if not filtered_outlets:
                    print(f"\n  {GREEN}Semua outlet sudah berhasil ditarik sebelumnya!{RESET}")
                    time.sleep(3)
                else:
                    selected_outlet = filtered_outlets
                    state = "confirm_all"
            else:
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(unique_outlets):
                        target_parent = unique_outlets[idx]
                        # Find all branches under this parent
                        matching_branches = [o for o in outlets if o['nama_outlet'] == target_parent]
                        
                        if len(matching_branches) == 1:
                            selected_outlet = matching_branches[0]
                            state = "confirm"
                        else:
                            parent_name = target_parent
                            branches = matching_branches
                            state = "select_branch"
                    else:
                        print(f"  {RED}Nomor outlet di luar jangkauan.{RESET}")
                        time.sleep(1)
                except ValueError:
                    print(f"  {RED}Pilihan tidak valid.{RESET}")
                    time.sleep(1)
                    
        elif state == "select_branch":
            os.system('cls' if os.name == 'nt' else 'clear')
            banner()
            print(f"  {BOLD}Pilih Cabang untuk '{parent_name}':{RESET}")
            print(f"    {GREEN}[all]{RESET} Jalankan semua cabang untuk outlet ini")
            print(f"    {GREEN}[new]{RESET} Jalankan HANYA cabang yang belum ditarik")
            
            for idx, b in enumerate(branches):
                branch_name = b['brand'] or b['nama_resto_final'] or b['merchant_name']
                print(f"    {GREEN}[{idx + 1:3d}]{RESET} {branch_name} (ID: {b['store_id']})")
                
            print(f"    {YELLOW}[b  ]{RESET} Kembali ke pemilihan outlet")
            print()
            
            choice = input(f"  {BOLD}Pilih nomor cabang (atau 'all'/'new'/'b'):{RESET} ").strip()
            if choice.lower() == 'b':
                state = "select_outlet"
            elif choice.lower() == 'all':
                selected_outlet = branches
                state = "confirm_all"
            elif choice.lower() == 'new':
                # Filter branches to keep only those that have not been run
                filtered_branches = []
                for o in branches:
                    raw_outlet = o.get('nama_outlet') or o.get('nama_resto_final') or o.get('merchant_name') or 'unknown'
                    clean_outlet = "".join(c for c in raw_outlet if c.isalnum() or c in (' ', '_', '-')).strip()
                    clean_outlet = re.sub(r'\s+', ' ', clean_outlet).lower()
                    
                    output_dir = get_output_dir(applicator, clean_outlet)
                    
                    is_processed = False
                    if os.path.exists(output_dir):
                        files = os.listdir(output_dir)
                        has_files = any(f.endswith('.csv') or f.endswith('.xlsx') for f in files)
                        if len(files) > 0 and has_files:
                            is_processed = True
                            
                    if not is_processed:
                        filtered_branches.append(o)
                
                if not filtered_branches:
                    print(f"\n  {GREEN}Semua cabang untuk outlet ini sudah berhasil ditarik sebelumnya!{RESET}")
                    time.sleep(3)
                else:
                    selected_outlet = filtered_branches
                    state = "confirm_all"
            else:
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(branches):
                        selected_outlet = branches[idx]
                        state = "confirm"
                    else:
                        print(f"  {RED}Nomor cabang di luar jangkauan.{RESET}")
                        time.sleep(1)
                except ValueError:
                    print(f"  {RED}Pilihan tidak valid.{RESET}")
                    time.sleep(1)
                    
        elif state == "confirm":
            os.system('cls' if os.name == 'nt' else 'clear')
            banner()
            print(f"  {CYAN}{'─'*60}{RESET}")
            print(f"  Aplikator : {BOLD}{applicator.upper()}{RESET}")
            name_to_show = selected_outlet['brand'] or selected_outlet['nama_resto_final'] or selected_outlet['nama_outlet']
            print(f"  Outlet    : {BOLD}{name_to_show}{RESET}")
            print(f"  Store ID  : {BOLD}{selected_outlet['store_id']}{RESET}")
            print(f"  {CYAN}{'─'*60}{RESET}")
            print()
            print(f"  {BOLD}Konfirmasi tindakan:{RESET}")
            print(f"    {GREEN}[1]{RESET} Lanjutkan Tarik Menu")
            print(f"    {YELLOW}[2]{RESET} Kembali ke daftar outlet")
            print(f"    {RED}[3]{RESET} Batal dan Keluar")
            print()
            
            choice = input(f"  {BOLD}Pilihan (1/2/3):{RESET} ").strip()
            if choice == "1":
                break
            elif choice == "2":
                state = "select_outlet"
            elif choice == "3":
                print("  Dibatalkan.")
                sys.exit(0)
            else:
                print(f"  {RED}Pilihan tidak valid.{RESET}")
                time.sleep(1)
                
        elif state == "confirm_all":
            os.system('cls' if os.name == 'nt' else 'clear')
            banner()
            
            # Count unprocessed outlets
            unprocessed_count = 0
            for o in selected_outlet:
                raw_outlet = o.get('nama_outlet') or o.get('nama_resto_final') or o.get('merchant_name') or 'unknown'
                clean_outlet = "".join(c for c in raw_outlet if c.isalnum() or c in (' ', '_', '-')).strip()
                clean_outlet = re.sub(r'\s+', ' ', clean_outlet).lower()
                
                output_dir = get_output_dir(applicator, clean_outlet)
                
                is_processed = False
                if os.path.exists(output_dir):
                    files = os.listdir(output_dir)
                    has_files = any(f.endswith('.csv') or f.endswith('.xlsx') for f in files)
                    if len(files) > 0 and has_files:
                        is_processed = True
                if not is_processed:
                    unprocessed_count += 1
            
            print(f"  {CYAN}{'─'*60}{RESET}")
            print(f"  Aplikator : {BOLD}{applicator.upper()}{RESET}")
            print(f"  Mode      : {BOLD}{YELLOW}BATCH RUN (Massal){RESET}")
            print(f"  Total     : {BOLD}{len(selected_outlet)} outlet/cabang{RESET}")
            print(f"  Belum Run : {BOLD}{GREEN}{unprocessed_count} outlet/cabang{RESET}")
            print(f"  Sudah Run : {BOLD}{len(selected_outlet) - unprocessed_count} outlet/cabang (Skipped jika pilih [2]){RESET}")
            print(f"  Jeda      : {BOLD}Setiap 10 outlet akan dijeda 1 menit{RESET}")
            print(f"  {CYAN}{'─'*60}{RESET}")
            print()
            print(f"  {BOLD}Konfirmasi tindakan:{RESET}")
            print(f"    {GREEN}[1]{RESET} Lanjutkan Jalankan SEMUA (Overwrite)")
            print(f"    {GREEN}[2]{RESET} Lanjutkan Jalankan HANYA yang Belum Selesai ({unprocessed_count} outlet)")
            print(f"    {YELLOW}[3]{RESET} Kembali ke daftar outlet")
            print(f"    {RED}[4]{RESET} Batal dan Keluar")
            print()
            
            choice = input(f"  {BOLD}Pilihan (1/2/3/4):{RESET} ").strip()
            if choice == "1":
                break
            elif choice == "2":
                filtered_outlets = []
                for o in selected_outlet:
                    raw_outlet = o.get('nama_outlet') or o.get('nama_resto_final') or o.get('merchant_name') or 'unknown'
                    clean_outlet = "".join(c for c in raw_outlet if c.isalnum() or c in (' ', '_', '-')).strip()
                    clean_outlet = re.sub(r'\s+', ' ', clean_outlet).lower()
                    
                    output_dir = get_output_dir(applicator, clean_outlet)
                    
                    is_processed = False
                    if os.path.exists(output_dir):
                        files = os.listdir(output_dir)
                        has_files = any(f.endswith('.csv') or f.endswith('.xlsx') for f in files)
                        if len(files) > 0 and has_files:
                            is_processed = True
                            
                    if not is_processed:
                        filtered_outlets.append(o)
                
                if not filtered_outlets:
                    print(f"\n  {GREEN}Semua outlet dalam batch ini sudah berhasil ditarik sebelumnya!{RESET}")
                    time.sleep(3)
                    state = "select_outlet"
                else:
                    selected_outlet = filtered_outlets
                    break
            elif choice == "3":
                state = "select_outlet"
            elif choice == "4":
                print("  Dibatalkan.")
                sys.exit(0)
            else:
                print(f"  {RED}Pilihan tidak valid.{RESET}")
                time.sleep(1)
                
    return applicator, selected_outlet


# ─────────────────────────────────────────────────────────────────────────────
# SHOPEE MENU MANAGER — Add / Edit menu interaktif
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_harga(rp: float) -> str:
    return f"Rp{int(rp):,}".replace(",", ".")


def _input_toggle(prompt: str, current: bool) -> bool:
    """Tanya user untuk toggle boolean, tampilkan nilai saat ini."""
    cur_str = f"{GREEN}Tersedia/Tampil{RESET}" if current else f"{RED}Habis/Sembunyikan{RESET}"
    ans = input(f"  {prompt} ({cur_str}) [y=aktif / n=nonaktif / Enter=sama]: ").strip().lower()
    if ans == 'y':
        return True
    elif ans == 'n':
        return False
    return current


def menu_manager_shopee():
    """Sub-menu interaktif untuk Add / Edit menu ShopeeFood."""
    # ── 1. Muat kredensial ShopeeFood dari credentials.json ──
    creds_path = os.path.join(MENU_DIR, "credentials.json")
    if not os.path.isfile(creds_path):
        print(f"  {RED}[ERROR] credentials.json tidak ditemukan di {creds_path}{RESET}")
        return

    with open(creds_path) as f:
        creds = json.load(f)

    sf = creds.get("ShopeeFood", {})
    store_metadata = {
        "store_id":       sf.get("StoreID", ""),
        "username":       sf.get("username", ""),
        "password":       sf.get("password", ""),
        "merchant_name":  sf.get("merchant_name", "SuperFood"),
        "nama_resto_final": "SuperFood",
        "nama_outlet":    "SuperFood",
        "nama_pendek":    "SuperFood",
        "brand":          "",
    }

    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        banner()
        print(f"  {BOLD}ShopeeFood — Menu Manager{RESET}")
        print(f"  Store ID: {CYAN}{store_metadata['store_id']}{RESET}")
        print()
        print(f"    {GREEN}[1]{RESET} Lihat daftar menu")
        print(f"    {GREEN}[2]{RESET} Tambah menu baru (Buat Menu)")
        print(f"    {GREEN}[3]{RESET} Edit menu (klik baris menu)")
        print(f"    {YELLOW}[4]{RESET} Kembali ke menu utama")
        print()
        choice = input(f"  {BOLD}Pilihan (1/2/3/4):{RESET} ").strip()

        if choice == "4":
            break

        elif choice == "1":
            # ── Lihat daftar menu ──
            print(f"\n  {CYAN}[*] Mengambil daftar menu...{RESET}")
            ok, result = list_menu_shopee(store_metadata)
            if not ok:
                print(f"  {RED}[ERROR] {result}{RESET}")
                input("  Tekan Enter untuk kembali...")
                continue

            dishes = result
            print(f"\n  {BOLD}Daftar Menu ({len(dishes)} item):{RESET}")
            print(f"  {'No':>4}  {'Nama Menu':<35} {'Harga':>12}  {'Stok':<10} {'Tampil':<10} Kategori")
            print(f"  {'─'*100}")
            for i, d in enumerate(dishes):
                stok_str   = f"{GREEN}Tersedia{RESET}" if d['available'] else f"{RED}Habis{RESET}"
                show_str   = f"{GREEN}Tampil{RESET}"   if d['show']      else f"{YELLOW}Sembunyikan{RESET}"
                print(
                    f"  {i+1:>4}. {d['nama']:<35} {_fmt_harga(d['harga']):>12}  "
                    f"{stok_str:<19} {show_str:<19} {d['category']}"
                )
            print()
            input("  Tekan Enter untuk kembali...")

        elif choice == "2":
            # ── TAMBAH MENU BARU ──
            print(f"\n  {BOLD}{GREEN}=== Tambah Menu Baru ==={RESET}")

            # Ambil kategori terlebih dahulu
            print(f"  {CYAN}[*] Mengambil kategori...{RESET}")
            client, store_id = _shopee_boot_client(store_metadata)
            if client is None:
                print(f"  {RED}[ERROR] {store_id}{RESET}")
                input("  Tekan Enter untuk kembali...")
                continue

            catalogs = client.get_store_dishes()
            if not catalogs:
                print(f"  {RED}Tidak ada kategori ditemukan.{RESET}")
                input("  Tekan Enter untuk kembali...")
                continue

            print(f"\n  {BOLD}Pilih Kategori:{RESET}")
            for i, cat in enumerate(catalogs):
                print(f"    {GREEN}[{i+1}]{RESET} {cat.get('name','?')} (ID: {cat.get('id','?')})")
            print()
            cat_choice = input(f"  Nomor kategori: ").strip()
            try:
                cat_idx = int(cat_choice) - 1
                if not (0 <= cat_idx < len(catalogs)):
                    raise ValueError
                selected_cat = catalogs[cat_idx]
            except ValueError:
                print(f"  {RED}Pilihan tidak valid.{RESET}")
                input("  Tekan Enter untuk kembali...")
                continue

            category_id = str(selected_cat.get("id", ""))
            print(f"  Kategori dipilih: {CYAN}{selected_cat.get('name')}{RESET}")
            print()

            # Input field
            nama = input(f"  Nama Menu: ").strip()
            if not nama:
                print(f"  {RED}Nama menu tidak boleh kosong.{RESET}")
                input("  Tekan Enter untuk kembali...")
                continue

            harga_str = input(f"  Harga (Rp): ").strip().replace(".", "").replace(",", "")
            try:
                harga = float(harga_str)
            except ValueError:
                print(f"  {RED}Harga tidak valid.{RESET}")
                input("  Tekan Enter untuk kembali...")
                continue

            deskripsi = input(f"  Deskripsi (opsional, Enter untuk kosong): ").strip()

            available  = _input_toggle("Ketersediaan Stok", True)
            show       = _input_toggle("Status Tampilan",  True)

            print(f"  Waktu Penjualan: {CYAN}Sepanjang hari{RESET} (default)")
            # Untuk sementara selalu sepanjang hari
            sales_time_type = 0

            image_path = input(f"  Path gambar lokal (opsional, Enter untuk skip): ").strip()
            if image_path and not os.path.isfile(image_path):
                print(f"  {YELLOW}[WARN] File gambar tidak ditemukan, dilewati.{RESET}")
                image_path = ""

            # Konfirmasi
            print(f"\n  {CYAN}{'─'*55}{RESET}")
            print(f"  Nama      : {BOLD}{nama}{RESET}")
            print(f"  Kategori  : {selected_cat.get('name')}")
            print(f"  Harga     : {_fmt_harga(harga)}")
            print(f"  Deskripsi : {deskripsi or '(kosong)'}")
            print(f"  Stok      : {'Tersedia' if available else 'Habis'}")
            print(f"  Tampilan  : {'Tampilkan' if show else 'Sembunyikan'}")
            print(f"  Waktu     : Sepanjang hari")
            print(f"  Gambar    : {image_path or '(tidak ada)'}")
            print(f"  {CYAN}{'─'*55}{RESET}")
            konfirm = input(f"  Lanjutkan? [y/n]: ").strip().lower()
            if konfirm != 'y':
                print(f"  {YELLOW}Dibatalkan.{RESET}")
                input("  Tekan Enter untuk kembali...")
                continue

            print(f"\n  {CYAN}[*] Menambahkan menu...{RESET}")
            ok, msg = add_menu_shopee(
                store_metadata=store_metadata,
                category_id=category_id,
                name=nama,
                price_rp=harga,
                description=deskripsi,
                available=available,
                show=show,
                image_path=image_path,
                sales_time_type=sales_time_type,
            )
            if ok:
                print(f"  {GREEN}{BOLD}✔ {msg}{RESET}")
            else:
                print(f"  {RED}{BOLD}✘ {msg}{RESET}")
            input("  Tekan Enter untuk kembali...")

        elif choice == "3":
            # ── EDIT MENU ──
            print(f"\n  {CYAN}[*] Mengambil daftar menu...{RESET}")
            ok, result = list_menu_shopee(store_metadata)
            if not ok:
                print(f"  {RED}[ERROR] {result}{RESET}")
                input("  Tekan Enter untuk kembali...")
                continue

            dishes = result
            if not dishes:
                print(f"  {YELLOW}Tidak ada menu yang tersedia.{RESET}")
                input("  Tekan Enter untuk kembali...")
                continue

            print(f"\n  {BOLD}Pilih Menu yang Ingin Diedit:{RESET}")
            print(f"  {'No':>4}  {'Nama Menu':<35} {'Harga':>12}  Kategori")
            print(f"  {'─'*75}")
            for i, d in enumerate(dishes):
                print(f"  {i+1:>4}. {d['nama']:<35} {_fmt_harga(d['harga']):>12}  {d['category']}")
            print()
            dish_choice = input(f"  Nomor menu (atau 'b' untuk kembali): ").strip()
            if dish_choice.lower() == 'b':
                continue
            try:
                dish_idx = int(dish_choice) - 1
                if not (0 <= dish_idx < len(dishes)):
                    raise ValueError
                selected_dish = dishes[dish_idx]
            except ValueError:
                print(f"  {RED}Pilihan tidak valid.{RESET}")
                input("  Tekan Enter untuk kembali...")
                continue

            # Tampilkan nilai saat ini
            print(f"\n  {BOLD}{GREEN}=== Edit Menu: {selected_dish['nama']} ==={RESET}")
            print(f"  (Tekan Enter untuk mempertahankan nilai saat ini)")
            print()

            nama = input(f"  Nama Menu [{selected_dish['nama']}]: ").strip()
            if not nama:
                nama = selected_dish['nama']

            harga_str = input(f"  Harga (Rp) [{_fmt_harga(selected_dish['harga'])}]: ").strip().replace(".", "").replace(",", "")
            if harga_str:
                try:
                    harga = float(harga_str)
                except ValueError:
                    print(f"  {RED}Harga tidak valid.{RESET}")
                    input("  Tekan Enter untuk kembali...")
                    continue
            else:
                harga = selected_dish['harga']

            deskripsi_default = selected_dish['deskripsi'] or '(kosong)'
            deskripsi = input(f"  Deskripsi [{deskripsi_default}]: ").strip()
            if not deskripsi and selected_dish['deskripsi']:
                deskripsi = selected_dish['deskripsi']

            available = _input_toggle("Ketersediaan Stok", selected_dish['available'])
            show      = _input_toggle("Status Tampilan",  selected_dish['show'])

            print(f"  Waktu Penjualan: {CYAN}Sepanjang hari{RESET} (default)")
            sales_time_type = 0

            image_path = input(f"  Path gambar baru (opsional, Enter untuk skip): ").strip()
            if image_path and not os.path.isfile(image_path):
                print(f"  {YELLOW}[WARN] File gambar tidak ditemukan, dilewati.{RESET}")
                image_path = ""

            # Konfirmasi
            print(f"\n  {CYAN}{'─'*55}{RESET}")
            print(f"  Dish ID   : {selected_dish['dish_id']}")
            print(f"  Nama      : {BOLD}{nama}{RESET}")
            print(f"  Kategori  : {selected_dish['category']}")
            print(f"  Harga     : {_fmt_harga(harga)}")
            print(f"  Deskripsi : {deskripsi or '(kosong)'}")
            print(f"  Stok      : {'Tersedia' if available else 'Habis'}")
            print(f"  Tampilan  : {'Tampilkan' if show else 'Sembunyikan'}")
            print(f"  Waktu     : Sepanjang hari")
            print(f"  Gambar    : {image_path or '(tidak diubah)'}")
            print(f"  {CYAN}{'─'*55}{RESET}")
            konfirm = input(f"  Lanjutkan simpan? [y/n]: ").strip().lower()
            if konfirm != 'y':
                print(f"  {YELLOW}Dibatalkan.{RESET}")
                input("  Tekan Enter untuk kembali...")
                continue

            print(f"\n  {CYAN}[*] Menyimpan perubahan...{RESET}")
            ok, msg = edit_menu_shopee(
                store_metadata=store_metadata,
                dish_id=selected_dish['dish_id'],
                category_id=selected_dish['category_id'],
                name=nama,
                price_rp=harga,
                description=deskripsi,
                available=available,
                show=show,
                image_path=image_path,
                sales_time_type=sales_time_type,
            )
            if ok:
                print(f"  {GREEN}{BOLD}✔ {msg}{RESET}")
            else:
                print(f"  {RED}{BOLD}✘ {msg}{RESET}")
            input("  Tekan Enter untuk kembali...")

        else:
            print(f"  {RED}Pilihan tidak valid.{RESET}")
            time.sleep(1)


def main():
    if os.environ.get("MENU_DISCORD_MODE") == "1":
        # Discord mode bypass
        target_app = os.environ.get("MENU_APLIKATOR", "shopee").lower()
        store_choice = os.environ.get("MENU_STORE_CHOICE", "all").lower()
        overwrite = os.environ.get("MENU_OVERWRITE") == "1"

        apps = ["shopee", "grab", "gofood"] if target_app == "all" else [target_app]

        for app in apps:
            print(f"\n{CYAN}=== MEMULAI EKSEKUSI DISCORD UNTUK PLATFORM: {app.upper()} ==={RESET}")
            try:
                outlets = get_outlets_for_applicator(app)
            except Exception as e:
                print(f"  {RED}[ERROR] Gagal memuat daftar outlet untuk {app.upper()}: {e}{RESET}")
                continue

            if not outlets:
                print(f"  {YELLOW}[WARN] Tidak ada outlet ditemukan untuk {app.upper()}{RESET}")
                continue

            # Resolve target outlet
            if store_choice == "all":
                target_outlets = outlets
            elif store_choice == "new":
                # Filter outlets to keep only those that have not been run (unless overwrite is true)
                filtered_outlets = []
                for o in outlets:
                    raw_outlet = o.get('nama_outlet') or o.get('nama_resto_final') or o.get('merchant_name') or 'unknown'
                    clean_outlet = "".join(c for c in raw_outlet if c.isalnum() or c in (' ', '_', '-')).strip()
                    clean_outlet = re.sub(r'\s+', ' ', clean_outlet).lower()
                    
                    output_dir = get_output_dir(app, clean_outlet)
                    
                    is_processed = False
                    if not overwrite and os.path.exists(output_dir):
                        files = os.listdir(output_dir)
                        has_files = any(f.endswith('.csv') or f.endswith('.xlsx') for f in files)
                        if len(files) > 0 and has_files:
                            is_processed = True
                    if not is_processed:
                        filtered_outlets.append(o)
                target_outlets = filtered_outlets
            else:
                selected_ids = [x.strip().lower() for x in store_choice.split(',') if x.strip()]
                target_outlets = [o for o in outlets if o['store_id'].strip().lower() in selected_ids]

            if not target_outlets:
                print(f"  {GREEN}Tidak ada outlet yang perlu diproses.{RESET}")
                continue

            # Run execution for target_outlets
            total_outlets = len(target_outlets)
            success_count = 0
            fail_count = 0

            for idx, o in enumerate(target_outlets):
                raw_outlet = o.get('nama_outlet') or o.get('nama_resto_final') or o.get('merchant_name') or 'unknown'
                clean_outlet = "".join(c for c in raw_outlet if c.isalnum() or c in (' ', '_', '-')).strip()
                clean_outlet = re.sub(r'\s+', ' ', clean_outlet).lower()
                
                output_dir = get_output_dir(app, clean_outlet)
                os.makedirs(output_dir, exist_ok=True)
                
                name_to_show = o['brand'] or o['nama_resto_final'] or o['nama_outlet']
                print(f"\n{BOLD}[{idx + 1}/{total_outlets}] Memproses: {name_to_show} (ID: {o['store_id']}){RESET}")
                
                success = False
                result_data = None
                
                try:
                    if app == "shopee":
                        success, result_data = extract_shopee_menu(o, output_dir)
                    elif app == "grab":
                        success, result_data = extract_grab_menu(o, output_dir)
                    elif app == "gofood":
                        success, result_data = extract_gofood_menu(o, output_dir)
                except Exception as e:
                    success = False
                    result_data = f"Exception occurred: {e}"
                    
                if success and isinstance(result_data, dict):
                    success_count += 1
                    print(f"  {GREEN}✔ Berhasil! {result_data.get('items_count', 0)} item, {result_data.get('mods_count', 0)} modifier.{RESET}")
                else:
                    fail_count += 1
                    print(f"  {RED}✘ Gagal: {result_data}{RESET}")
                    
                if (idx + 1) < total_outlets and (idx + 1) % 10 == 0:
                    print(f"\n{YELLOW}[BATCH] Selesai memproses 10 outlet. Menunggu jeda 1 menit...{RESET}")
                    time.sleep(60)

            print(f"\n{CYAN}=== SELESAI PLATFORM: {app.upper()} ==={RESET}")
            print(f"  - Sukses : {GREEN}{success_count}{RESET}")
            print(f"  - Gagal  : {RED}{fail_count}{RESET}")
        return

    try:
        applicator, outlet = interactive_menu()
    except KeyboardInterrupt:
        print("\n  Dibatalkan oleh pengguna.")
        sys.exit(0)

    if isinstance(outlet, list):
        total_outlets = len(outlet)
        print(f"\n{CYAN}=== MEMULAI PENARIKAN MENU MASSAL ({total_outlets} OUTLET) ==={RESET}")
        print(f"[*] Waktu mulai: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        success_count = 0
        fail_count = 0
        
        for idx, o in enumerate(outlet):
            raw_outlet = o.get('nama_outlet') or o.get('nama_resto_final') or o.get('merchant_name') or 'unknown'
            clean_outlet = "".join(c for c in raw_outlet if c.isalnum() or c in (' ', '_', '-')).strip()
            clean_outlet = re.sub(r'\s+', ' ', clean_outlet).lower()
            
            output_dir = get_output_dir(applicator, clean_outlet)
            os.makedirs(output_dir, exist_ok=True)
            
            name_to_show = o['brand'] or o['nama_resto_final'] or o['nama_outlet']
            print(f"\n{BOLD}[{idx + 1}/{total_outlets}] Memproses: {name_to_show} (ID: {o['store_id']}){RESET}")
            
            success = False
            result_data = None
            
            try:
                if applicator == "shopee":
                    success, result_data = extract_shopee_menu(o, output_dir)
                elif applicator == "grab":
                    success, result_data = extract_grab_menu(o, output_dir)
                elif applicator == "gofood":
                    success, result_data = extract_gofood_menu(o, output_dir)
            except Exception as e:
                success = False
                result_data = f"Exception occurred: {e}"
                
            if success and isinstance(result_data, dict):
                success_count += 1
                print(f"  {GREEN}✔ Berhasil! {result_data.get('items_count', 0)} item, {result_data.get('mods_count', 0)} modifier.{RESET}")
            else:
                fail_count += 1
                print(f"  {RED}✘ Gagal: {result_data}{RESET}")
                
            # Delay logic: 1 minute pause after every 10 outlets
            if (idx + 1) < total_outlets and (idx + 1) % 10 == 0:
                print(f"\n{YELLOW}[BATCH] Selesai memproses 10 outlet. Menunggu jeda 1 menit sebelum batch berikutnya...{RESET}")
                for remaining in range(60, 0, -1):
                    sys.stdout.write(f"\rMenunggu... {remaining} detik")
                    sys.stdout.flush()
                    time.sleep(1)
                print(f"\r{GREEN}[BATCH] Jeda selesai. Melanjutkan penarikan...{RESET}\n")
                
        print(f"\n{CYAN}=== PENARIKAN MENU MASSAL SELESAI ==={RESET}")
        print(f"  - Sukses : {GREEN}{success_count}{RESET}")
        print(f"  - Gagal  : {RED}{fail_count}{RESET}")
        
    else:
        print(f"\n{CYAN}=== MEMULAI PENARIKAN MENU ==={RESET}")
        print(f"[*] Waktu mulai: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        raw_outlet = outlet.get('nama_outlet') or outlet.get('nama_resto_final') or outlet.get('merchant_name') or 'unknown'
        clean_outlet = "".join(c for c in raw_outlet if c.isalnum() or c in (' ', '_', '-')).strip()
        clean_outlet = re.sub(r'\s+', ' ', clean_outlet).lower()
        
        output_dir = get_output_dir(applicator, clean_outlet)
        os.makedirs(output_dir, exist_ok=True)
        
        success = False
        result_data = None
        
        if applicator == "shopee":
            success, result_data = extract_shopee_menu(outlet, output_dir)
        elif applicator == "grab":
            success, result_data = extract_grab_menu(outlet, output_dir)
        elif applicator == "gofood":
            success, result_data = extract_gofood_menu(outlet, output_dir)
            
        if success and isinstance(result_data, dict):
            print(f"\n{GREEN}{BOLD}✔ PENARIKAN MENU BERHASIL!{RESET}")
            print(f"  - Total Item     : {result_data['items_count']}")
            print(f"  - Total Modifier : {result_data['mods_count']}")
            print(f"  - Hasil disimpan di directory: {output_dir}")
            print(f"    1. Items CSV     : {result_data['items_csv']}")
            print(f"    2. Modifiers CSV : {result_data['mods_csv']}")
            print(f"    3. Excel Unified : {result_data['excel']}")
        else:
            print(f"\n{RED}{BOLD}✘ PENARIKAN MENU GAGAL / STUB{RESET}")
            if isinstance(result_data, str):
                print(f"  Info: {result_data}")
            
if __name__ == "__main__":
    main()
