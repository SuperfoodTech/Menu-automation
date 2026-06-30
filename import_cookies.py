import os
import json
import sys
from pathlib import Path
from datetime import datetime

WEEKLY_DIR = Path("/home/akbarhann/project/task-weekly/weekly")

def parse_and_save_cookies(raw_cookie_str: str):
    raw_cookie_str = raw_cookie_str.strip()
    # Remove surrounding quotes if pasted with them
    if (raw_cookie_str.startswith('"') and raw_cookie_str.endswith('"')) or (raw_cookie_str.startswith("'") and raw_cookie_str.endswith("'")):
        raw_cookie_str = raw_cookie_str[1:-1]
        
    pairs = raw_cookie_str.split("; ")
    cookies = {}
    for p in pairs:
        if "=" in p:
            k, v = p.split("=", 1)
            cookies[k.strip()] = v.strip()
            
    tob_token = cookies.get("shopee_tob_token", "")
    entity_id = cookies.get("shopee_tob_entity_id", "")
    
    if not tob_token:
        print("[!] Warning: shopee_tob_token not found in the cookie string!")
        
    session_data = {
        "shopee_tob_token": tob_token,
        "shopee_tob_entity_id": entity_id,
        "saved_at": datetime.now().isoformat(),
        "extra_cookies": cookies
    }
    
    session_file = WEEKLY_DIR / "data" / "session.json"
    os.makedirs(session_file.parent, exist_ok=True)
    with open(session_file, "w") as f:
        json.dump(session_data, f, indent=2)
        
    print(f"[+] Successfully saved {len(cookies)} cookies to {session_file}")
    print(f"    shopee_tob_token: {tob_token[:30]}...")
    print(f"    shopee_tob_entity_id: {entity_id}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_cookies.py <raw_cookie_string>")
        sys.exit(1)
    parse_and_save_cookies(sys.argv[1])
