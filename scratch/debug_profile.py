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
    # Use Chrome profile from weekly/data/chrome_profile
    profile_dir = WEEKLY_DIR / "data" / "chrome_profile"
    
    # Remove SingletonLock to prevent lock issues on Linux
    singleton_lock = profile_dir / "SingletonLock"
    if singleton_lock.exists() or singleton_lock.is_symlink():
        try:
            singleton_lock.unlink(missing_ok=True)
            print(f"[*] Removed SingletonLock")
        except Exception as e:
            print(f"[!] Failed to remove lock: {e}")
            
    options.add_argument(f"--user-data-dir={profile_dir.resolve()}")
    options.add_argument("--profile-directory=shopee_profile")
    
    # Run in headless mode to inspect state
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    
    print("[*] Launching Chrome...")
    driver = webdriver.Chrome(options=options)
    
    try:
        print("[*] Navigating to https://partner.shopee.co.id/shopee-pos ...")
        driver.get("https://partner.shopee.co.id/shopee-pos")
        time.sleep(5)
        
        print(f"[+] Current URL: {driver.current_url}")
        
        # Take a screenshot to see what's on the screen
        screenshot_path = "/home/akbarhann/project/task-weekly/menu/shopee/data_to_get/debug_screenshot.png"
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
        driver.save_screenshot(screenshot_path)
        print(f"[+] Screenshot saved to: {screenshot_path}")
        
        # Print all cookies
        cookies = driver.get_cookies()
        print("\n[+] Cookies found:")
        cookies_dict = {}
        for c in cookies:
            name = c['name']
            val = c['value']
            cookies_dict[name] = val
            # truncate token for clean print
            print(f"    {name}: {val[:50]}..." if len(val) > 50 else f"    {name}: {val}")
            
        # Write cookies to a temporary file
        temp_cookies_path = "/home/akbarhann/project/task-weekly/menu/shopee/data_to_get/debug_cookies.json"
        with open(temp_cookies_path, "w") as f:
            json.dump(cookies_dict, f, indent=2)
        print(f"\n[+] Cookies written to: {temp_cookies_path}")
        
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
