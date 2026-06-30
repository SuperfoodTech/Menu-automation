import sys
import time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

WEEKLY_DIR = Path("/home/akbarhann/project/task-weekly/weekly")
sys.path.insert(0, str(WEEKLY_DIR))

from core import browser

def main():
    # Construct sub-account username
    username = "Depotnasipenyetanlonta_allvbadmin"
    password = "Shopee@321"
    
    print(f"[*] Testing Direct Login for Sub-account: {username}")
    
    # We will use get_session, which handles the login flow automatically
    # But we will use a temporary session file so we don't mess up others
    temp_session = WEEKLY_DIR / "data" / "session_test_lontar.json"
    browser.set_session_file(temp_session)
    
    # Delete the temp session file to force login
    if temp_session.exists():
        temp_session.unlink()
        
    print("[*] Launching browser and performing login...")
    session_data = browser.get_session(
        username=username,
        password=password,
        headless=True,
        close_browser=True,
        target_name=None, # Don't try to switch, just login
        interactive=False
    )
    
    if session_data and "shopee_tob_token" in session_data:
        print("\n[+] LOGIN SUCCESSFUL WITH SUB-ACCOUNT!")
        print(f"    Token: {session_data['shopee_tob_token'][:30]}...")
        print(f"    Entity ID: {session_data.get('shopee_tob_entity_id')}")
        
        # Verify the entity ID matches Lontar (1205626)
        # Note: the entity ID might be in the cookies
        print("\n[+] Extra Cookies:")
        for k, v in session_data.get("extra_cookies", {}).items():
            if "id" in k.lower():
                print(f"    {k}: {v}")
    else:
        print("\n[-] LOGIN FAILED!")

if __name__ == "__main__":
    main()
