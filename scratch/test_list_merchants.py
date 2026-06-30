import sys
from pathlib import Path
from selenium.webdriver.chrome.options import Options

# Add shopee-omzet-automation to sys.path
AUTOMATION_DIR = Path("/home/akbarhann/project/task-weekly/src/shopee-omzet-automation")
if str(AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(AUTOMATION_DIR))

from core import browser

# Patch Options
orig_add_argument = Options.add_argument
def custom_add_argument(self, argument):
    if "--user-data-dir=" in argument:
        argument = "--user-data-dir=/home/akbarhann/project/task-weekly/weekly/data/chrome_profile"
    orig_add_argument(self, argument)
Options.add_argument = custom_add_argument

def main():
    print("[*] Launching browser to list merchants...")
    session_file = Path("/home/akbarhann/project/task-weekly/weekly/data/session.json")
    browser.set_session_file(session_file)
    
    # Do not pass target_name so it runs _handle_merchant_selection
    browser.get_session(
        username="allvbadmin",
        password="Shopee@321",
        headless=True,
        close_browser=True,
        target_name=None,
        interactive=False
    )

if __name__ == "__main__":
    main()
