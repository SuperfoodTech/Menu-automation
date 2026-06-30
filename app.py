# Trigger reload after credentials.json update
import os
import sys
import json
import uuid
import time
import datetime
import csv
import io
import pandas as pd
from fastapi import FastAPI, BackgroundTasks, HTTPException, Body
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker



# Setup paths to import menu_core modules
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from shopee.core.edit import _boot_client, edit_dish_via_portal
from adapter_factory import get_adapter

DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'menu_management.db')}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ──────────────────────────────────────────────
# Database Models
# ──────────────────────────────────────────────

class Outlet(Base):
    __tablename__ = "outlets"
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(String, unique=True, index=True)
    platform = Column(String, default="shopee")  # 'shopee', 'grab'
    mgid = Column(String, nullable=True)          # Grab Merchant Group ID
    username = Column(String)
    password = Column(String)
    merchant_name = Column(String)
    session_status = Column(String, default="Active")
    last_sync_at = Column(DateTime, nullable=True)

class Category(Base):
    __tablename__ = "categories"
    id = Column(String, primary_key=True)
    store_id = Column(String, ForeignKey("outlets.store_id"))
    name = Column(String)
    sequence = Column(Integer, default=0)
    sync_status = Column(String, default="synced") # 'synced', 'pending_create', 'pending_update'

class Dish(Base):
    __tablename__ = "dishes"
    id = Column(String, primary_key=True)
    category_id = Column(String, ForeignKey("categories.id"))
    name = Column(String)
    price_rp = Column(Float)
    description = Column(Text, default="")
    available = Column(Boolean, default=True)
    show = Column(Boolean, default=True)
    image_url = Column(String, default="")
    stock_type = Column(Integer, default=0) # 0: Unlimited, 1: Limited
    stock_limit_current = Column(Integer, default=0)
    sync_status = Column(String, default="synced") # 'synced', 'pending_metadata', 'failed'

class SyncJob(Base):
    __tablename__ = "sync_jobs"
    id = Column(String, primary_key=True)
    store_id = Column(String)
    status = Column(String, default="pending") # 'pending', 'processing', 'completed', 'failed'
    progress_step = Column(Integer, default=0) # 0 to 4
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

Base.metadata.create_all(bind=engine)

# Schema Migration
try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE categories ADD COLUMN sync_status VARCHAR DEFAULT 'synced';"))
        conn.commit()
        print("Column sync_status added to categories table.")
except Exception as e:
    pass

try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE dishes ADD COLUMN stock_type INTEGER DEFAULT 0;"))
        conn.commit()
        print("Column stock_type added to dishes table.")
except Exception as e:
    pass

try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE dishes ADD COLUMN stock_limit_current INTEGER DEFAULT 0;"))
        conn.commit()
        print("Column stock_limit_current added to dishes table.")
except Exception as e:
    pass

try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE outlets ADD COLUMN platform VARCHAR DEFAULT 'shopee';"))
        conn.commit()
        print("Column platform added to outlets table.")
except Exception as e:
    pass

try:
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE outlets ADD COLUMN mgid VARCHAR;"))
        conn.commit()
        print("Column mgid added to outlets table.")
except Exception as e:
    pass

# ──────────────────────────────────────────────
# Database Seeder (Seed outlets from credentials.json — multi-platform)
# ──────────────────────────────────────────────

def seed_database():
    db = SessionLocal()
    try:
        creds_path = os.path.join(BASE_DIR, "credentials.json")
        if not os.path.exists(creds_path):
            print("⚠ credentials.json not found. Skipping seeder.")
            return
            
        with open(creds_path) as f:
            creds = json.load(f)

        platform_map = {
            "ShopeeFood": "shopee",
            "GrabFood": "grab",
        }

        for key, platform in platform_map.items():
            app_data = creds.get(key, {})
            store_id = app_data.get("StoreID", "")
            if not store_id:
                continue

            exists = db.query(Outlet).filter(Outlet.store_id == store_id).first()
            if not exists:
                new_outlet = Outlet(
                    store_id=store_id,
                    platform=platform,
                    username=app_data.get("username", app_data.get("email", "")),
                    password=app_data.get("password", ""),
                    merchant_name=f"Automate_{key}",
                    session_status="Active"
                )
                db.add(new_outlet)
                print(f"✔ Seeded {platform} store ID {store_id} into database.")
            else:
                # Update platform if missing
                if not exists.platform or exists.platform == 'shopee' and platform != 'shopee':
                    pass  # Don't overwrite existing
                elif exists.platform != platform:
                    pass  # Already seeded
        db.commit()
    except Exception as e:
        print(f"Error seeding database: {e}")
    finally:
        db.close()

seed_database()

# ──────────────────────────────────────────────
# Background Tasks (Sync / Pull operations)
# ──────────────────────────────────────────────

def background_pull_all_stores(username_sf: str, password_sf: str):
    db = SessionLocal()
    try:
        # We boot client with temporary store id just to login
        store_metadata = {
            "store_id":       "21941677",  # bootstrap store id
            "username":       username_sf,
            "password":       password_sf,
            "merchant_name":  "Bootstrap",
        }
        client, _ = _boot_client(store_metadata, headless=True)
        if not client:
            print("Failed to boot Shopee client for listing stores")
            return
            
        stores = client.get_stores()
        if not stores:
            print("No stores returned from Shopee API")
            return
            
        for store in stores:
            s_id = str(store.get("id"))
            s_name = store.get("name")
            
            exists = db.query(Outlet).filter(Outlet.store_id == s_id).first()
            if exists:
                exists.merchant_name = s_name
            else:
                new_outlet = Outlet(
                    store_id=s_id,
                    platform="shopee",
                    username=username_sf,
                    password=password_sf,
                    merchant_name=s_name,
                    session_status="Active"
                )
                db.add(new_outlet)
        db.commit()
        print(f"✔ Successfully pulled and saved {len(stores)} outlets from Shopee API.")
    except Exception as e:
        print(f"Error pulling stores from API: {e}")
    finally:
        db.close()

def background_pull_all_stores_grab(username: str, password: str):
    """Pull all stores from GrabFood using the GrabAdapter."""
    db = SessionLocal()
    try:
        adapter = get_adapter("grab")
        stores = adapter.pull_stores(username, password)
        if not stores:
            print("No stores returned from GrabFood API")
            return

        for store in stores:
            s_id = store.get("store_id")
            s_name = store.get("merchant_name")
            s_mgid = store.get("mgid")

            exists = db.query(Outlet).filter(Outlet.store_id == s_id).first()
            if exists:
                exists.merchant_name = s_name
                exists.mgid = s_mgid
            else:
                new_outlet = Outlet(
                    store_id=s_id,
                    platform="grab",
                    mgid=s_mgid,
                    username=username,
                    password=password,
                    merchant_name=s_name,
                    session_status="Active"
                )
                db.add(new_outlet)
        db.commit()
        print(f"✔ Successfully pulled and saved {len(stores)} outlets from GrabFood API.")
    except Exception as e:
        print(f"Error pulling GrabFood stores: {e}")
    finally:
        db.close()

def background_pull_dishes(store_id: str):
    db = SessionLocal()
    try:
        outlet = db.query(Outlet).filter(Outlet.store_id == store_id).first()
        if not outlet:
            return

        platform = getattr(outlet, 'platform', 'shopee') or 'shopee'

        if platform == "grab":
            # Use GrabAdapter for pull
            adapter = get_adapter("grab")
            categories = adapter.pull_dishes(outlet)
        else:
            # Shopee — existing logic
            store_metadata = {
                "store_id":       outlet.store_id,
                "username":       outlet.username,
                "password":       outlet.password,
                "merchant_name":  outlet.merchant_name,
                "nama_resto_final": outlet.merchant_name,
                "nama_outlet":    outlet.merchant_name,
                "nama_pendek":    outlet.merchant_name,
                "brand":          "",
            }
            
            client, _ = _boot_client(store_metadata, headless=True)
            if not client:
                raise Exception("Failed to boot Shopee client")
                
            raw_catalogs = client.get_store_dishes()
            if not raw_catalogs:
                raise Exception("No categories returned from Shopee")
            
            # Normalize to adapter format
            categories = []
            for cat in raw_catalogs:
                normalized = {
                    "id": str(cat.get("id")),
                    "name": cat.get("name"),
                    "sequence": cat.get("sequence", 0),
                    "items": [],
                }
                for dish in cat.get("dishes", []):
                    normalized["items"].append({
                        "id": str(dish.get("id")),
                        "name": dish.get("name"),
                        "price_rp": float(dish.get("price", 0)) / 100000.0,
                        "description": dish.get("description", ""),
                        "available": bool(dish.get("available")),
                        "show": bool(dish.get("show", True)),
                        "image_url": dish.get("picture", ""),
                        "stock_type": int(dish.get("stock_type", 0)),
                        "stock_limit_current": int(dish.get("stock_limit_current", 0)),
                    })
                categories.append(normalized)

        # Clean existing dishes and categories for this store
        db.query(Dish).filter(Dish.category_id.in_(
            db.query(Category.id).filter(Category.store_id == store_id)
        )).delete(synchronize_session=False)
        db.query(Category).filter(Category.store_id == store_id).delete(synchronize_session=False)
        
        # Insert normalized categories and dishes
        for cat in categories:
            new_cat = Category(
                id=str(cat["id"]),
                store_id=store_id,
                name=cat["name"],
                sequence=cat.get("sequence", 0)
            )
            db.add(new_cat)
            
            for item in cat.get("items", []):
                new_dish = Dish(
                    id=str(item["id"]),
                    category_id=str(cat["id"]),
                    name=item["name"],
                    price_rp=item["price_rp"],
                    description=item.get("description", ""),
                    available=item.get("available", True),
                    show=item.get("show", True),
                    image_url=item.get("image_url", ""),
                    stock_type=int(item.get("stock_type", 0)),
                    stock_limit_current=int(item.get("stock_limit_current", 0)),
                    sync_status="synced"
                )
                db.add(new_dish)
                
        outlet.last_sync_at = datetime.datetime.now()
        db.commit()
        print(f"✔ Successfully pulled and saved {store_id} ({platform}) menu to SQLite.")
    except Exception as e:
        print(f"Error pulling dishes: {e}")
    finally:
        db.close()

def background_sync_changes(job_id: str, store_id: str):
    db = SessionLocal()
    try:
        job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
        if not job:
            return
            
        job.status = "processing"
        job.progress_step = 1  # Step 1: Connecting client
        db.commit()
        
        outlet = db.query(Outlet).filter(Outlet.store_id == store_id).first()
        platform = getattr(outlet, 'platform', 'shopee') or 'shopee'
        
        if platform == "grab":
            job.progress_step = 2  # Step 2: Sending edits via API
            db.commit()
            
            pending_categories = db.query(Category).filter(
                Category.store_id == store_id,
                Category.sync_status.in_(["pending_create", "pending_update"])
            ).all()
            
            pending_dishes = db.query(Dish).filter(
                Dish.category_id.in_(db.query(Category.id).filter(Category.store_id == store_id)),
                Dish.sync_status.in_(["pending_metadata", "pending_create"])
            ).all()
            
            adapter = get_adapter("grab")
            sync_errors = adapter.sync_changes(db, outlet, pending_categories, pending_dishes)
        else:
            store_metadata = {
                "store_id":       outlet.store_id,
                "username":       outlet.username,
                "password":       outlet.password,
                "merchant_name":  outlet.merchant_name,
                "nama_resto_final": outlet.merchant_name,
                "nama_outlet":    outlet.merchant_name,
                "nama_pendek":    outlet.merchant_name,
                "brand":          "",
            }
                
            # Boot Shopee Partner client (API)
            client, api_store_id = _boot_client(store_metadata, headless=True)
            if not client:
                raise Exception(f"Gagal login/koneksi API: {api_store_id}")

            job.progress_step = 2  # Step 2: Sending edits via API
            db.commit()
            
            sync_errors = []

            # 2a. Sync pending categories first
            pending_categories = db.query(Category).filter(
                Category.store_id == store_id,
                Category.sync_status.in_(["pending_create", "pending_update"])
            ).all()
            
            for cat in pending_categories:
                if cat.sync_status == "pending_create":
                    new_cat_data = client.create_category(store_id, cat.name)
                    if new_cat_data and "id" in new_cat_data:
                        real_id = str(new_cat_data["id"])
                        old_id = cat.id
                        
                        # Update category ID in categories and dishes tables
                        db.execute(
                            text("UPDATE categories SET id = :new_id, sync_status = 'synced' WHERE id = :old_id"),
                            {"new_id": real_id, "old_id": old_id}
                        )
                        db.execute(
                            text("UPDATE dishes SET category_id = :new_id WHERE category_id = :old_id"),
                            {"new_id": real_id, "old_id": old_id}
                        )
                        db.commit()
                        print(f"  [Sync] Category '{cat.name}' created on Shopee. ID changed from {old_id} to {real_id}")
                    else:
                        err_msg = f"Gagal membuat kategori '{cat.name}': {client.last_error}" if client.last_error else f"Gagal membuat kategori '{cat.name}'"
                        print(f"  [Sync] {err_msg}")
                        cat.sync_status = "failed"
                        db.commit()
                        sync_errors.append(err_msg)
                elif cat.sync_status == "pending_update":
                    ok = client.update_category(store_id, cat.id, cat.name)
                    if ok:
                        cat.sync_status = "synced"
                        print(f"  [Sync] Category ID {cat.id} updated name to '{cat.name}' on Shopee")
                    else:
                        err_msg = f"Gagal memperbarui kategori '{cat.name}': {client.last_error}" if client.last_error else f"Gagal memperbarui kategori '{cat.name}'"
                        print(f"  [Sync] {err_msg}")
                        cat.sync_status = "failed"
                        sync_errors.append(err_msg)
                    db.commit()

            # 2b. Get all dishes with pending updates or creations
            pending_dishes = db.query(Dish).filter(
                Dish.category_id.in_(db.query(Category.id).filter(Category.store_id == store_id)),
                Dish.sync_status.in_(["pending_metadata", "pending_create"])
            ).all()
            
            for dish in pending_dishes:
                if dish.sync_status == "pending_create":
                    # Create via API
                    res_data = client.create_dish(
                        store_id=store_id,
                        category_id=dish.category_id,
                        name=dish.name,
                        price_rp=dish.price_rp,
                        description=dish.description or "",
                        available=dish.available,
                        show=dish.show,
                        picture="",
                        sales_time_type=0,
                        stock_type=dish.stock_type,
                        stock_limit_current=dish.stock_limit_current,
                    )
                    if res_data:
                        real_id = None
                        if "id" in res_data:
                            real_id = str(res_data["id"])
                        elif "dish" in res_data and "id" in res_data["dish"]:
                            real_id = str(res_data["dish"]["id"])
                            
                        if real_id:
                            old_id = dish.id
                            db.execute(
                                text("UPDATE dishes SET id = :new_id, sync_status = 'synced' WHERE id = :old_id"),
                                {"new_id": real_id, "old_id": old_id}
                            )
                            db.commit()
                            print(f"  [Sync] Dish '{dish.name}' created on Shopee. ID changed from {old_id} to {real_id}")
                        else:
                            err_msg = f"Gagal memproses ID menu baru '{dish.name}': Respon tidak valid"
                            print(f"  [Sync] {err_msg}")
                            dish.sync_status = "failed"
                            db.commit()
                            sync_errors.append(err_msg)
                    else:
                        err_msg = f"Gagal membuat menu '{dish.name}': {client.last_error}" if client.last_error else f"Gagal membuat menu '{dish.name}'"
                        print(f"  [Sync] {err_msg}")
                        dish.sync_status = "failed"
                        db.commit()
                        sync_errors.append(err_msg)
                elif dish.sync_status == "pending_metadata":
                    # Sync via API update
                    ok = client.update_dish(
                        store_id=store_id,
                        dish_id=dish.id,
                        category_id=dish.category_id,
                        name=dish.name,
                        price_rp=dish.price_rp,
                        description=dish.description or "",
                        available=dish.available,
                        show=dish.show,
                        picture="",
                        sales_time_type=0,
                        stock_type=dish.stock_type,
                        stock_limit_current=dish.stock_limit_current,
                    )
                    if ok:
                        print(f"  [Sync] {dish.name}: Berhasil diupdate via API")
                        dish.sync_status = "synced"
                    else:
                        err_msg = f"Gagal memperbarui menu '{dish.name}': {client.last_error}" if client.last_error else f"Gagal memperbarui menu '{dish.name}'"
                        print(f"  [Sync] {err_msg}")
                        dish.sync_status = "failed"
                        sync_errors.append(err_msg)
                    db.commit()
            
        job.progress_step = 3  # Step 3: Portal edits completed
        db.commit()
        time.sleep(1)
        
        job.progress_step = 4  # Step 4: Finalizing
        if sync_errors:
            job.status = "failed"
            job.error_message = "; ".join(sync_errors)
        else:
            job.status = "completed"
            job.error_message = ""
        db.commit()
    except Exception as e:
        print(f"Error syncing changes: {e}")
        job.status = "failed"
        job.error_message = str(e)
        db.commit()
    finally:
        db.close()

# ──────────────────────────────────────────────
# FastAPI App Definition & Routes
# ──────────────────────────────────────────────

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_index():
    return FileResponse("static/index.html")

@app.get("/api/outlets")
def get_outlets(platform: str = None):
    db = SessionLocal()
    query = db.query(Outlet)
    if platform:
        query = query.filter(Outlet.platform == platform)
    outlets = query.all()
    db.close()
    return outlets

@app.get("/api/platform/{platform}/capabilities")
def get_platform_capabilities(platform: str):
    """Return capabilities for a given platform."""
    try:
        adapter = get_adapter(platform)
        return {
            "platform": platform,
            "supports_write": adapter.supports_write,
            "supports_sync": adapter.supports_write,
            "supports_export": True,
            "supports_pull": True,
        }
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Platform tidak didukung: {platform}")

@app.post("/api/outlets/pull-all")
def pull_all_outlets(background_tasks: BackgroundTasks, platform: str = "shopee"):
    db = SessionLocal()
    outlet = db.query(Outlet).filter(Outlet.platform == platform).first()
    db.close()
    
    if not outlet:
        creds_path = os.path.join(BASE_DIR, "credentials.json")
        if os.path.exists(creds_path):
            with open(creds_path) as f:
                creds = json.load(f)
            platform_key = {"shopee": "ShopeeFood", "grab": "GrabFood"}.get(platform, "ShopeeFood")
            app_data = creds.get(platform_key, {})
            username = app_data.get("username", app_data.get("email", ""))
            password = app_data.get("password", "")
        else:
            raise HTTPException(status_code=400, detail="No credentials available")
    else:
        username = outlet.username
        password = outlet.password

    if platform == "shopee":
        background_tasks.add_task(background_pull_all_stores, username, password)
    elif platform == "grab":
        background_tasks.add_task(background_pull_all_stores_grab, username, password)
    else:
        raise HTTPException(status_code=400, detail=f"Platform tidak didukung: {platform}")
    return {"status": "started", "platform": platform}

@app.get("/api/outlets/{store_id}/dishes")
def get_dishes(store_id: str):
    db = SessionLocal()
    dishes = db.query(Dish, Category.name.label("category_name")).join(
        Category, Dish.category_id == Category.id
    ).filter(Category.store_id == store_id).all()
    
    result = []
    for dish, cat_name in dishes:
        result.append({
            "id": dish.id,
            "category_id": dish.category_id,
            "category_name": cat_name,
            "name": dish.name,
            "price_rp": dish.price_rp,
            "description": dish.description,
            "available": dish.available,
            "show": dish.show,
            "image_url": dish.image_url,
            "stock_type": dish.stock_type,
            "stock_limit_current": dish.stock_limit_current,
            "sync_status": dish.sync_status
        })
    db.close()
    return result

@app.get("/api/outlets/{store_id}/export")
def export_dishes_excel(store_id: str):
    db = SessionLocal()
    outlet = db.query(Outlet).filter(Outlet.store_id == store_id).first()
    if not outlet:
        db.close()
        raise HTTPException(status_code=404, detail="Outlet not found")
    
    platform = getattr(outlet, 'platform', 'shopee') or 'shopee'
    db.close()

    try:
        adapter = get_adapter(platform)
        df_items, df_mods = adapter.export_menu(outlet)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export gagal: {str(e)}")

    # Write to Excel in memory
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        df_items.to_excel(writer, sheet_name='Items', index=False)
        df_mods.to_excel(writer, sheet_name='Modifiers', index=False)
    
    excel_buffer.seek(0)
    
    return StreamingResponse(
        excel_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={platform}_menu_{store_id}.xlsx"}
    )

@app.post("/api/outlets/{store_id}/pull")
def pull_dishes(store_id: str, background_tasks: BackgroundTasks):
    background_tasks.add_task(background_pull_dishes, store_id)
    return {"status": "started"}

@app.post("/api/dishes/bulk-price")
def bulk_price(payload: dict = Body(...)):
    db = SessionLocal()
    dish_ids = payload.get("dish_ids", [])
    adjustment = payload.get("adjustment", "")
    
    if not dish_ids:
        db.close()
        raise HTTPException(status_code=400, detail="No dishes selected")
        
    dishes = db.query(Dish).filter(Dish.id.in_(dish_ids)).all()
    for dish in dishes:
        price = dish.price_rp
        if adjustment.startswith("+"):
            val = float(adjustment.replace("+", "").replace("%", ""))
            if adjustment.endswith("%"):
                price = price * (1 + val / 100)
            else:
                price += val
        elif adjustment.startswith("-"):
            val = float(adjustment.replace("-", "").replace("%", ""))
            if adjustment.endswith("%"):
                price = price * (1 - val / 100)
            else:
                price -= val
        else:
            price = float(adjustment)
            
        dish.price_rp = round(price)
        dish.sync_status = "pending_metadata"
    db.commit()
    db.close()
    return {"status": "success"}

@app.post("/api/dishes/toggle-availability")
def toggle_availability(payload: dict = Body(...)):
    db = SessionLocal()
    dish_id = payload.get("dish_id")
    available = payload.get("available")
    
    dish = db.query(Dish).filter(Dish.id == dish_id).first()
    if not dish:
        db.close()
        raise HTTPException(status_code=404, detail="Dish not found")
        
    dish.available = available
    dish.sync_status = "pending_metadata"
    db.commit()
    db.close()
    return {"status": "success"}

@app.post("/api/dishes/toggle-show")
def toggle_show(payload: dict = Body(...)):
    db = SessionLocal()
    dish_id = payload.get("dish_id")
    show = payload.get("show")
    
    dish = db.query(Dish).filter(Dish.id == dish_id).first()
    if not dish:
        db.close()
        raise HTTPException(status_code=404, detail="Dish not found")
        
    dish.show = show
    dish.sync_status = "pending_metadata"
    db.commit()
    db.close()
    return {"status": "success"}

@app.post("/api/dishes/{dish_id}/update")
def update_dish_fields(dish_id: str, payload: dict = Body(...)):
    db = SessionLocal()
    dish = db.query(Dish).filter(Dish.id == dish_id).first()
    if not dish:
        db.close()
        raise HTTPException(status_code=404, detail="Dish not found")
        
    if "name" in payload:
        dish.name = payload["name"]
    if "price_rp" in payload:
        dish.price_rp = float(payload["price_rp"])
    if "description" in payload:
        dish.description = payload["description"]
    if "available" in payload:
        dish.available = bool(payload["available"])
    if "show" in payload:
        dish.show = bool(payload["show"])
    if "category_id" in payload:
        dish.category_id = payload["category_id"]
    if "stock_type" in payload:
        dish.stock_type = int(payload["stock_type"])
    if "stock_limit_current" in payload:
        dish.stock_limit_current = int(payload["stock_limit_current"])
        
    dish.sync_status = "pending_metadata"
    db.commit()
    db.close()
    return {"status": "success"}
@app.get("/api/outlets/{store_id}/categories")
def get_categories(store_id: str):
    db = SessionLocal()
    categories = db.query(Category).filter(Category.store_id == store_id).order_by(Category.sequence).all()
    result = []
    for cat in categories:
        result.append({
            "id": cat.id,
            "store_id": cat.store_id,
            "name": cat.name,
            "sequence": cat.sequence,
            "sync_status": cat.sync_status
        })
    db.close()
    return result

@app.post("/api/outlets/{store_id}/categories")
def create_local_category(store_id: str, payload: dict = Body(...)):
    db = SessionLocal()
    name = payload.get("name")
    if not name:
        db.close()
        raise HTTPException(status_code=400, detail="Category name is required")
        
    temp_id = "temp_" + str(uuid.uuid4())
    new_cat = Category(
        id=temp_id,
        store_id=store_id,
        name=name,
        sync_status="pending_create"
    )
    db.add(new_cat)
    db.commit()
    db.refresh(new_cat)
    result = {
        "id": new_cat.id,
        "store_id": new_cat.store_id,
        "name": new_cat.name,
        "sync_status": new_cat.sync_status
    }
    db.close()
    return result

@app.post("/api/categories/{category_id}/update")
def update_local_category(category_id: str, payload: dict = Body(...)):
    db = SessionLocal()
    name = payload.get("name")
    if not name:
        db.close()
        raise HTTPException(status_code=400, detail="Category name is required")
        
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        db.close()
        raise HTTPException(status_code=404, detail="Category not found")
        
    cat.name = name
    if cat.sync_status != "pending_create":
        cat.sync_status = "pending_update"
        
    db.commit()
    db.close()
    return {"status": "success"}

@app.post("/api/outlets/{store_id}/dishes")
def create_local_dish(store_id: str, payload: dict = Body(...)):
    db = SessionLocal()
    category_id = payload.get("category_id")
    name = payload.get("name")
    price_rp = payload.get("price_rp")
    
    if not category_id or not name or price_rp is None:
        db.close()
        raise HTTPException(status_code=400, detail="Missing required fields: category_id, name, price_rp")
        
    temp_id = "temp_dish_" + str(uuid.uuid4())
    new_dish = Dish(
        id=temp_id,
        category_id=category_id,
        name=name,
        price_rp=float(price_rp),
        description=payload.get("description", ""),
        available=payload.get("available", True),
        show=payload.get("show", True),
        stock_type=int(payload.get("stock_type", 0)),
        stock_limit_current=int(payload.get("stock_limit_current", 0)),
        sync_status="pending_create"
    )
    db.add(new_dish)
    db.commit()
    db.refresh(new_dish)
    result = {
        "id": new_dish.id,
        "category_id": new_dish.category_id,
        "name": new_dish.name,
        "price_rp": new_dish.price_rp,
        "description": new_dish.description,
        "available": new_dish.available,
        "show": new_dish.show,
        "stock_type": new_dish.stock_type,
        "stock_limit_current": new_dish.stock_limit_current,
        "sync_status": new_dish.sync_status
    }
    db.close()
    return result

@app.get("/api/outlets/{store_id}/ping-session")
def ping_outlet_session(store_id: str):
    db = SessionLocal()
    outlet = db.query(Outlet).filter(Outlet.store_id == store_id).first()
    if not outlet:
        db.close()
        raise HTTPException(status_code=404, detail="Outlet not found")
    
    platform = getattr(outlet, 'platform', 'shopee') or 'shopee'
    db.close()

    try:
        adapter = get_adapter(platform)
        return adapter.ping_session(outlet)
    except Exception as e:
        return {"active": False, "msg": str(e)}


@app.post("/api/outlets/{store_id}/sync")
def sync_changes(store_id: str, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    db = SessionLocal()
    new_job = SyncJob(id=job_id, store_id=store_id, status="pending")
    db.add(new_job)
    db.commit()
    db.close()
    
    background_tasks.add_task(background_sync_changes, job_id, store_id)
    return {"job_id": job_id}

@app.get("/api/sync-jobs/{job_id}")
def get_sync_job(job_id: str):
    db = SessionLocal()
    job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
    db.close()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@app.get("/api/sync-jobs")
def get_all_sync_jobs():
    db = SessionLocal()
    jobs = db.query(SyncJob).order_by(SyncJob.created_at.desc()).limit(100).all()
    db.close()
    return jobs

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)
