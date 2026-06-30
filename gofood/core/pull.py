import os
import json
import re
import sys
import pandas as pd

def extract_gofood_menu(store_metadata: dict, output_dir: str):
    """
    Extracts menu for GoFood by running the login and redirect flow to intercept the menu API response.
    """
    store_id = store_metadata.get('store_id', '')
    nama_resto = store_metadata.get('nama_resto_final') or store_metadata.get('nama_outlet') or ''
    brand = store_metadata.get('brand') or ''
    
    print(f"\n[GoFood Menu Extractor]")
    print(f"[-] Target Outlet: {nama_resto} ({store_id})")
    
    # 1. Jalankan login_outlet untuk membuka browser, masuk dashboard, dan menangkap API menu
    # Tambahkan path agar bisa mengimpor login_gofood
    menu_dir = str(Path(__file__).resolve().parents[2])
    if menu_dir not in sys.path:
        sys.path.insert(0, menu_dir)
        
    try:
        from login_gofood import login_outlet
        print(f"[*] Meluncurkan browser untuk login GoFood & pengalihan ke halaman menu...")
        login_result = login_outlet(store_metadata)
        if not login_result or not login_result.get('access_token'):
            print(f"[!] Login atau penarikan menu dibatalkan/gagal.")
            return False, "Proses login/intersepsi menu via browser gagal atau dibatalkan."
    except Exception as e:
        print(f"[!] Terjadi kesalahan saat menjalankan browser login: {e}")
        return False, f"Terjadi kesalahan saat meluncurkan browser login: {e}"
        
    # 2. Simpan dan load data menu yang ditangkap
    api_dir = os.path.join(menu_dir, "gofood", "docs", "API")
    os.makedirs(api_dir, exist_ok=True)
    json_path = os.path.join(api_dir, f"menu-response-{store_id}.json")
    
    captured_menu = login_result.get('captured_menu')
    if not captured_menu:
        print("[!] Gagal menangkap data menu dari browser pada sesi ini.")
        return False, "Gagal menangkap data menu dari browser pada sesi ini."
        
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(captured_menu, f, indent=4)
        print(f"   💾 Menu response berhasil disimpan ke: {json_path}")
    except Exception as e:
        print(f"   ⚠️ Gagal menyimpan menu response ke file: {e}")
            
    captured_modifiers = login_result.get('captured_modifiers')
    if captured_modifiers:
        try:
            mod_json_path = os.path.join(api_dir, f"modifier-response-{store_id}.json")
            with open(mod_json_path, 'w', encoding='utf-8') as f:
                json.dump({"variant_categories": captured_modifiers}, f, indent=4)
            print(f"   💾 Modifier response hasil intercept berhasil disimpan ke: {mod_json_path}")
        except Exception as e:
            print(f"   ⚠️ Gagal menyimpan modifier response ke file: {e}")
        
    print(f"[*] Memuat data menu dari: {json_path}")
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return False, f"Gagal membaca file JSON menu: {e}"
        
    menus = data.get("menus", [])
    if not menus:
        return False, "Data menu kosong di dalam file JSON."
        
    # --- LOAD MODIFIER DATA ---
    modifier_path = os.path.join(api_dir, f"modifier-response-{store_id}.json")
        
    variant_categories_map = {}
    if os.path.exists(modifier_path):
        try:
            with open(modifier_path, 'r', encoding='utf-8') as f:
                mod_data = json.load(f)
            for m_cat in mod_data.get("variant_categories", []):
                # Map by id (local v1 ID)
                vid = m_cat.get("id")
                if vid:
                    variant_categories_map[vid] = m_cat
                # Map by common_id (v2 common ID)
                cid = m_cat.get("common_id")
                if cid:
                    variant_categories_map[cid] = m_cat
                # Map by master_variant_category_id (v1 master ID)
                mcid = m_cat.get("master_variant_category_id")
                if mcid:
                    variant_categories_map[mcid] = m_cat
            print(f"   💾 Loaded {len(variant_categories_map)} keys in variant categories map from {modifier_path}")
        except Exception as e:
            print(f"   ⚠️ Gagal memuat data modifier dari {modifier_path}: {e}")
            
    all_dishes = []
    modifier_rows = []
    
    # Parse GoFood menu categories and items
    for cat in menus:
        cat_name = cat.get("name", "").strip()
        cat_active = cat.get("active", True)
        if not cat_active:
            continue
            
        items = cat.get("menu_items", [])
        for item in items:
            item_name = item.get("name", "").strip()
            item_price_str = item.get("price", "0")
            try:
                item_price = float(item_price_str)
            except ValueError:
                item_price = 0.0
                
            item_desc = item.get("description", "").strip()
            item_active = item.get("active", True)
            item_instock = item.get("in_stock", True)
            
            ketersediaan = "Tersedia" if (item_active and item_instock) else "Habis"
            
            # Cari link foto
            img_url = ""
            if item.get("image"):
                img_url = item["image"]
            elif item.get("image_cover") and isinstance(item["image_cover"], dict):
                img_url = item["image_cover"].get("url", "")
                
            # Modifier groups count
            var_cat_ids = item.get("variant_category_ids", [])
            mod_groups_count = len(var_cat_ids)
            total_modifiers_count = 0
            
            # Count modifiers & gather rows
            for vcat_id in var_cat_ids:
                vcat = variant_categories_map.get(vcat_id)
                if not vcat:
                    continue
                
                variants = vcat.get("variants", [])
                total_modifiers_count += len(variants)
                
                vcat_name = vcat.get("name", "").strip()
                rules = vcat.get("rules") or {}
                selection = rules.get("selection") or {}
                min_qty = selection.get("min_quantity", 0)
                max_qty = selection.get("max_quantity", 0)
                tipe_modifier = "Pilihan Tunggal" if max_qty == 1 else "Pilihan Ganda"
                
                for var in variants:
                    var_name = var.get("name", "").strip()
                    var_price = float(var.get("price", 0))
                    var_active = var.get("active", True)
                    var_instock = var.get("in_stock", True)
                    var_ketersediaan = "Tersedia" if (var_active and var_instock) else "Habis"
                    
                    modifier_rows.append([
                        f"https://gofood.link/a/{store_id}",
                        nama_resto,
                        brand or nama_resto,
                        store_id,
                        item_name,
                        vcat_name,
                        var_name,
                        tipe_modifier,
                        min_qty,
                        max_qty,
                        var_price,
                        var_ketersediaan
                    ])
            
            # Robust promotion parsing if present in API response
            promo_info = item.get("promotion")
            harga_sebelum = item_price
            harga_setelah = item_price
            promo_val = 0
            
            if isinstance(promo_info, dict):
                disc_price = promo_info.get("discounted_price") or promo_info.get("price") or promo_info.get("promo_price")
                if disc_price:
                    try:
                        harga_setelah = float(disc_price)
                    except ValueError:
                        pass
                
                pct = promo_info.get("discount_percentage") or promo_info.get("percentage")
                val = promo_info.get("discount_value") or promo_info.get("value") or promo_info.get("amount")
                if pct:
                    promo_val = f"{int(pct)}%"
                elif val:
                    try:
                        promo_val = f"Rp {int(float(val))}"
                    except ValueError:
                        pass
                else:
                    if harga_sebelum > harga_setelah and harga_sebelum > 0:
                        diff = harga_sebelum - harga_setelah
                        promo_val = f"{int(round(diff / harga_sebelum * 100))}%"
            
            dish_obj = {
                'link_outlet': f"https://gofood.link/a/{store_id}",
                'nama_panjang': nama_resto,
                'nama_pendek': brand or nama_resto,
                'store_id': store_id,
                'nama_kategori': cat_name,
                'nama_item': item_name,
                'jumlah_terjual': 0,
                'jumlah_modifier_group': mod_groups_count,
                'jumlah_modifier': total_modifiers_count,
                'deskripsi_item': item_desc,
                'harga_sebelum_promo': harga_sebelum,
                'harga_setelah_promo': harga_setelah,
                'promo': promo_val,
                'ketersediaan': ketersediaan,
                'link_foto': img_url
            }
            all_dishes.append(dish_obj)
            
    # Build output DataFrames
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
            d['harga_setelah_promo'], d['promo'], "", "", "", d['ketersediaan'], d['link_foto']
        ])
        
    df_items = pd.DataFrame(item_data, columns=item_cols)
    
    mod_cols = [
        'Link outlet', 'Nama panjang', 'Nama pendek (ShopeeFood)', 'Store ID',
        'Nama item', 'Nama modifier group', 'Nama modifier', 'Tipe modifier',
        'Minimal', 'Maksimal', 'Harga modifier', 'Ketersediaan modifier'
    ]
    
    df_mods = pd.DataFrame(modifier_rows, columns=mod_cols)
    
    # Write to files
    os.makedirs(output_dir, exist_ok=True)
    
    def clean_name(s):
        cleaned = "".join(c for c in s if c.isalnum() or c in (' ', '_', '-')).rstrip()
        return cleaned.replace(' ', '_')
        
    safe_merchant = clean_name(nama_resto)
    branch_raw = store_metadata.get('brand') or store_metadata.get('nama_resto_final') or store_metadata.get('nama_outlet') or ""
    safe_branch = clean_name(branch_raw)
    
    if safe_branch.lower() == safe_merchant.lower() or not safe_branch:
        combined_name = safe_merchant
    else:
        combined_name = f"{safe_merchant}_{safe_branch}"
        
    combined_name = re.sub(r'_+', '_', combined_name)
    
    items_csv_path = os.path.join(output_dir, f"gofood_items_{combined_name}_{store_id}.csv")
    mods_csv_path = os.path.join(output_dir, f"gofood_modifiers_{combined_name}_{store_id}.csv")
    excel_path = os.path.join(output_dir, f"gofood_menu_{combined_name}_{store_id}.xlsx")
    
    df_items.to_csv(items_csv_path, index=False)
    df_mods.to_csv(mods_csv_path, index=False)
    
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        df_items.to_excel(writer, sheet_name='Items', index=False)
        df_mods.to_excel(writer, sheet_name='Modifiers', index=False)
        
    print(f"   ✅ Berhasil memproses data menu GoFood!")
    print(f"      - Item Count: {len(df_items)}")
    return True, {
        'items_csv': items_csv_path,
        'mods_csv': mods_csv_path,
        'excel': excel_path,
        'items_count': len(df_items),
        'mods_count': len(df_mods)
    }
