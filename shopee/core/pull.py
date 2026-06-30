# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import pandas as pd
from pathlib import Path
from .client import ShopeeClient, ShopeeModifyClient

WORKSPACE_DIR = Path(__file__).resolve().parents[3]
AUTOMATION_DIR = WORKSPACE_DIR / "src" / "shopee-omzet-automation"
if str(AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_DIR))
from core import browser

IMG_BASE = "https://down-id.img.susercontent.com/file"

def list_menu_shopee(store_metadata: dict) -> tuple[bool, list | str]:
    from .edit import _boot_client
    client, err = _boot_client(store_metadata, headless=True)
    if not client:
        return False, f"Boot client failed: {err}"
        
    store_id = store_metadata["store_id"]
    catalogs = client.get_store_dishes(store_id)
    return True, catalogs

def extract_shopee_menu(store_metadata: dict, output_dir: str):
    store_id = store_metadata['store_id']
    m_name = store_metadata.get('merchant_name', '')
    if not m_name or m_name.lower() == 'nan' or m_name == '-':
        target_name = store_metadata.get('nama_resto_final') or store_metadata.get('nama_outlet') or ''
    else:
        target_name = m_name
        
    nama_pendek = store_metadata.get('nama_pendek') or target_name
    
    session_file = WORKSPACE_DIR / "weekly" / "data" / "session.json"
    browser.set_session_file(session_file)
    
    username = store_metadata.get("username", "allvbadmin")
    password = store_metadata.get("password", "Shopee@321")
            
    print(f"[*] Membuka browser (headless=True) dan memilih merchant: '{target_name}'...")
    session_data = browser.get_session(
        username=username,
        password=password,
        headless=True,
        close_browser=False,
        target_name=target_name,
        interactive=False
    )
    
    if not session_data or "driver" not in session_data:
        return False, "Gagal menginisialisasi browser atau memilih merchant."
        
    driver = session_data["driver"]
    try:
        from .edit import _sync_store_session
        print("[*] Memperbarui token autentikasi untuk merchant terpilih...")
        _sync_store_session(driver, store_id)
        session = browser.refresh_tokens(driver, fallback_entity_id=store_id)
        if not session or "shopee_tob_token" not in session:
            return False, "Gagal memperbarui token autentikasi."
            
        tob_token = session["shopee_tob_token"]
        extra_cookies = session.get("extra_cookies", {})
        
        try:
            driver.quit()
        except:
            pass
            
        client = ShopeeClient(
            tob_token=tob_token,
            entity_id=store_id,
            extra_cookies=extra_cookies
        )
        
        print(f"[*] Menarik data menu ShopeeFood untuk: {target_name} ({store_id})...")
        catalogs = client.get_store_dishes(store_id)
        if not catalogs:
            return False, "Tidak ada data catalog/dishes yang ditemukan. Periksa session."
            
        print(f"[*] Ditemukan {len(catalogs)} kategori menu.")
        all_dishes = []
        dish_ids_with_modifiers = []
        
        for cat in catalogs:
            cat_name = cat.get('name', 'Menu Lainnya')
            dishes = cat.get('dishes', [])
            for dish in dishes:
                dish_id = str(dish.get('id'))
                dish_name = dish.get('name', '')
                price_raw = dish.get('price', '0')
                list_price_raw = dish.get('list_price', '0')
                description = dish.get('description', '')
                available = dish.get('available', True)
                opt_group_count = dish.get('option_group_count', 0)
                sales_volume = dish.get('sales_volume', 0)
                picture = dish.get('picture', '')
                discount_pct = dish.get('discount_percentage', 0)
                
                price = float(price_raw) / 100000.0
                list_price = float(list_price_raw) / 100000.0 if (list_price_raw and float(list_price_raw) > 0) else price
                
                promo_val = ""
                if discount_pct > 0:
                    promo_val = f"{int(discount_pct / 100)}%"
                elif list_price > price:
                    promo_val = f"{int(round((list_price - price) / list_price * 100))}%"
                    
                flash_sale_price = ""
                flash_sale_pct = ""
                flash_sale_stock = ""
                
                flash_sale_dish_discount = dish.get('flash_sale_dish_discount')
                if flash_sale_dish_discount and isinstance(flash_sale_dish_discount, dict):
                    discount_info = flash_sale_dish_discount.get('discount')
                    if discount_info and isinstance(discount_info, dict):
                        is_deleted = discount_info.get('is_deleted', 0)
                        discount_status = discount_info.get('discount_status', 1)
                        if is_deleted == 0 and discount_status == 1:
                            fs_price_val = discount_info.get('discount_price')
                            if fs_price_val:
                                flash_sale_price = float(fs_price_val) / 100000.0
                            pct_val = discount_info.get('discount_percentage')
                            if pct_val:
                                flash_sale_pct = f"{int(pct_val / 100)}%"
                            flash_sale_stock = discount_info.get('stock', "")
                elif dish.get('flash_sale_price') and float(dish.get('flash_sale_price')) > 0:
                    flash_sale_price = float(dish.get('flash_sale_price')) / 100000.0
                    
                available_str = "Tersedia" if available else "Habis"
                picture_url = f"{IMG_BASE}/{picture}" if picture else ""
                link_outlet = f"https://shopee.co.id/now-food/shop/{store_id}"
                
                dish_info = {
                    'link_outlet': link_outlet,
                    'nama_panjang': target_name,
                    'nama_pendek': nama_pendek,
                    'store_id': store_id,
                    'nama_kategori': cat_name,
                    'nama_item': dish_name,
                    'jumlah_terjual': sales_volume,
                    'opt_group_count': opt_group_count,
                    'deskripsi_item': description,
                    'harga_sebelum_promo': list_price,
                    'harga_setelah_promo': price,
                    'promo': promo_val,
                    'harga_flash_sale': flash_sale_price,
                    'promo_flash_sale': flash_sale_pct,
                    'stok_flash_sale': flash_sale_stock,
                    'ketersediaan': available_str,
                    'link_foto': picture_url,
                    'dish_id': dish_id,
                    'jumlah_modifier_group': 0,
                    'jumlah_modifier': 0
                }
                all_dishes.append(dish_info)
                
                if opt_group_count > 0:
                    dish_ids_with_modifiers.append(dish_id)

        print(f"[*] Total {len(all_dishes)} item ditemukan.")
        print(f"[*] Menarik modifier untuk {len(dish_ids_with_modifiers)} item yang memiliki topping/opsi...")
        
        modifier_rows = []
        for dish_id in dish_ids_with_modifiers:
            dish_obj = next((d for d in all_dishes if d['dish_id'] == dish_id), None)
            if not dish_obj:
                continue
                
            opt_groups = client.get_store_option_groups(store_id, dish_ids=[dish_id])
            dish_obj['jumlah_modifier_group'] = len(opt_groups)
            total_modifiers_count = 0
            
            for group in opt_groups:
                opt_group_info = group.get('option_group', {})
                group_name = opt_group_info.get('name', '').strip()
                select_min = opt_group_info.get('select_min', 0)
                select_max = opt_group_info.get('select_max', 0)
                options = group.get('options', [])
                
                total_modifiers_count += len(options)
                tipe_modifier = "Pilihan Tunggal" if select_max == 1 else "Pilihan Ganda"
                
                for opt in options:
                    opt_name = opt.get('name', '')
                    opt_price = float(opt.get('price', '0')) / 100000.0
                    opt_available = opt.get('available', True)
                    opt_available_str = "Tersedia" if opt_available else "Habis"
                    
                    modifier_rows.append({
                        'link_outlet': dish_obj['link_outlet'],
                        'nama_panjang': target_name,
                        'nama_pendek': nama_pendek,
                        'store_id': store_id,
                        'nama_item': dish_obj['nama_item'],
                        'nama_modifier_group': group_name,
                        'nama_modifier': opt_name,
                        'tipe_modifier': tipe_modifier,
                        'minimal': select_min,
                        'maksimal': select_max,
                        'harga_modifier': opt_price,
                        'ketersediaan_modifier': opt_available_str
                    })
            
            dish_obj['jumlah_modifier'] = total_modifiers_count
            
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
        os.makedirs(output_dir, exist_ok=True)
        
        import re
        def clean_name(s):
            cleaned = "".join(c for c in s if c.isalnum() or c in (' ', '_', '-')).rstrip()
            return cleaned.replace(' ', '_')
            
        safe_merchant = clean_name(target_name)
        branch_raw = store_metadata.get('brand') or store_metadata.get('nama_resto_final') or store_metadata.get('nama_outlet') or ""
        safe_branch = clean_name(branch_raw)
        
        if safe_branch.lower() == safe_merchant.lower() or not safe_branch:
            combined_name = safe_merchant
        else:
            combined_name = f"{safe_merchant}_{safe_branch}"
            
        combined_name = re.sub(r'_+', '_', combined_name)
        
        items_csv_path = os.path.join(output_dir, f"shopee_items_{combined_name}_{store_id}.csv")
        mods_csv_path = os.path.join(output_dir, f"shopee_modifiers_{combined_name}_{store_id}.csv")
        excel_path = os.path.join(output_dir, f"shopee_menu_{combined_name}_{store_id}.xlsx")
        
        df_items.to_csv(items_csv_path, index=False)
        df_mods.to_csv(mods_csv_path, index=False)
        
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            df_items.to_excel(writer, sheet_name='Items', index=False)
            df_mods.to_excel(writer, sheet_name='Modifiers', index=False)
            
        return True, {
            'items_csv': items_csv_path,
            'mods_csv': mods_csv_path,
            'excel': excel_path,
            'items_count': len(df_items),
            'mods_count': len(df_mods)
        }
    except Exception as e:
        try:
            driver.quit()
        except:
            pass
        return False, f"Error selama ekstraksi menu: {e}"
