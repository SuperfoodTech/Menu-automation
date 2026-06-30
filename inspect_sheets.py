import sys
import os
from pathlib import Path

# Add menu_core to sys.path
sys.path.insert(0, str(Path("/home/akbarhann/project/task-weekly/menu")))

from menu_core.sheets import get_master_df

def main():
    df = get_master_df()
    print("[*] Columns in GSheet:")
    print(df.columns.tolist())
    
    # Filter for ShopeeFood
    shopee_df = df[df['Aplikasi'].str.strip().str.lower().str.contains('shopee', na=False)].copy()
    print(f"\n[*] Total ShopeeFood outlets: {len(shopee_df)}")
    
    # Let's inspect some rows
    cols_to_show = ['Store ID', 'Nama Resto Final', 'Nama Outlet', 'Aplikasi', 'Status']
    # If there are credential columns, show them
    cred_cols = [c for c in df.columns if any(kw in c.lower() for kw in ['user', 'pass', 'sandi', 'login', 'phone', 'hp', 'username', 'password'])]
    cols_to_show.extend(cred_cols)
    
    # Clean list of cols
    cols_to_show = [c for c in cols_to_show if c in df.columns]
    
    print(f"\n[*] Displaying first 10 ShopeeFood rows:")
    print(shopee_df[cols_to_show].head(10).to_string())

if __name__ == "__main__":
    main()
