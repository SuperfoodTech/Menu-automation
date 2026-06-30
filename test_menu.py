import sys
import os

# Add parent directory of menu_core to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from menu_core.sheets import get_outlets_for_applicator
from menu_core.shopee import extract_shopee_menu

def main():
    print("[*] Testing sheets loader...")
    try:
        outlets = get_outlets_for_applicator("shopee")
        print(f"[+] Loaded {len(outlets)} ShopeeFood outlets.")
        if not outlets:
            print("[!] No outlets found. Exiting test.")
            return
            
        # Let's search for the first active store or use the first one
        # Let's find one that we know exists in the account, e.g. "Depot Nasi Penyetan - Lontar" or similar.
        test_outlet = None
        for o in outlets:
            if "lontar" in o['nama_resto_final'].lower():
                test_outlet = o
                break
        
        if not test_outlet:
            test_outlet = outlets[0]
            
        print(f"[*] Selecting outlet for test: {test_outlet['nama_resto_final']} (ID: {test_outlet['store_id']})")
        
        raw_outlet = test_outlet.get('nama_outlet') or test_outlet.get('nama_resto_final') or test_outlet.get('merchant_name') or 'unknown'
        import re
        clean_outlet = "".join(c for c in raw_outlet if c.isalnum() or c in (' ', '_', '-')).strip()
        clean_outlet = re.sub(r'\s+', ' ', clean_outlet).lower()
        output_dir = f"/home/akbarhann/project/task-weekly/menu/shopee/outlets/{clean_outlet}"
        success, result = extract_shopee_menu(test_outlet, output_dir)
        print(f"[*] Result: Success={success}, Data={result}")
    except Exception as e:
        print(f"[ERROR] Test failed with exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
