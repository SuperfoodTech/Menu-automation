import sys
from pathlib import Path

sys.path.insert(0, str(Path("/home/akbarhann/project/task-weekly/menu")))
from menu_core.sheets import get_master_df

def main():
    df = get_master_df()
    shopee_df = df[df['Aplikasi'].str.strip().str.lower().str.contains('shopee', na=False)]
    
    # Search for Lontar
    lontar = shopee_df[shopee_df['Nama Resto Final'].str.lower().str.contains('lontar', na=False)]
    
    if len(lontar) == 0:
        print("[!] Lontar not found")
        return
        
    print("[*] Found Lontar:")
    row = lontar.iloc[0]
    for col in df.columns:
        val = row.get(col, '')
        if val and str(val).strip() and str(val).strip() != '-':
            print(f"  {col}: {val}")

if __name__ == "__main__":
    main()
