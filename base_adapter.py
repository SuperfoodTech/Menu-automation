from abc import ABC, abstractmethod


class PlatformAdapter(ABC):
    """
    Base class untuk semua platform adapter.
    Setiap platform (Shopee, Grab, dll) harus implementasi interface ini.
    """

    platform_name: str = "unknown"

    @abstractmethod
    def pull_stores(self, username: str, password: str) -> list[dict]:
        """
        Ambil daftar toko dari platform.
        Return: list of {store_id, merchant_name, ...}
        """
        pass

    @abstractmethod
    def pull_dishes(self, outlet) -> list[dict]:
        """
        Ambil data menu (kategori + item) dari platform.
        Return: list of category dicts, masing-masing punya 'items'.
        Format standar:
        [
            {
                "id": "cat_id",
                "name": "Kategori Nama",
                "sequence": 0,
                "items": [
                    {
                        "id": "item_id",
                        "name": "Nama Item",
                        "price_rp": 15000.0,
                        "description": "...",
                        "available": True,
                        "show": True,
                        "image_url": "https://...",
                        "stock_type": 0,
                        "stock_limit_current": 0,
                    }
                ]
            }
        ]
        """
        pass

    @abstractmethod
    def export_menu(self, outlet) -> tuple:
        """
        Export menu dalam format (df_items, df_mods) DataFrames.
        Return: (pd.DataFrame, pd.DataFrame)
        """
        pass

    @abstractmethod
    def ping_session(self, outlet) -> dict:
        """
        Cek apakah session masih aktif.
        Return: {"active": bool, "msg": str}
        """
        pass

    def sync_changes(self, outlet, pending_dishes, pending_categories) -> list[str]:
        """
        Push perubahan lokal ke platform.
        Default: tidak didukung (read-only).
        Return: list of error messages.
        """
        return [f"Platform {self.platform_name} belum mendukung sync/publish."]

    @property
    def supports_write(self) -> bool:
        """Apakah platform ini mendukung operasi write (create/update/delete)."""
        return False
