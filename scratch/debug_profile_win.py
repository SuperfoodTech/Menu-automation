import os
import sys
import time
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# Add weekly to sys.path
WEEKLY_DIR = Path("/home/akbarhann/project/task-weekly/weekly")
sys.path.insert(0, str(WEEKLY_DIR))

def main():
    options = Options()
    # FORCE chrome_profile_win just like the weekly dashboard script
    profile_dir = WEEKLY_DIR / "data" / "chrome_profile_win"
    
    # Remove SingletonLock
    singleton_lock = profile_dir / "SingletonLock"
    if singleton_lock.exists() or singleton_lock.is_symlink():
        try:
            singleton_lock.unlink(missing_ok=True)
        except:
            pass
            
    options.add_argument(f"--user-data-dir={profile_dir.resolve()}")
    options.add_argument("--profile-directory=shopee_profile")
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    
    print("[*] Launching Chrome with chrome_profile_win...")
    driver = webdriver.Chrome(options=options)
    
    try:
        print("[*] Navigating to https://partner.shopee.co.id/shopee-pos ...")
        driver.get("https://partner.shopee.co.id/shopee-pos")
        time.sleep(5)
        
        print(f"[+] Current URL: {driver.current_url}")
        
        screenshot_path = "/home/akbarhann/project/task-weekly/menu/shopee/data_to_get/debug_win_screenshot.png"
        driver.save_screenshot(screenshot_path)
        print(f"[+] Screenshot saved to: {screenshot_path}")
        
        cookies = driver.get_cookies()
        tob_token = next((c['value'] for c in cookies if c['name'] == 'shopee_tob_token'), None)
        entity_id = next((c['value'] for c in cookies if c['name'] == 'shopee_tob_entity_id'), None)
        print(f"[+] shopee_tob_token: {tob_token[:30] + '...' if tob_token else 'NOT FOUND'}")
        print(f"[+] shopee_tob_entity_id: {entity_id}")
        
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
