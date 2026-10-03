
from flask import Flask, render_template, request, redirect, flash
import pandas as pd
import os
from flask import jsonify
import threading
import time
import json
import sqlite3
DB_FILE = os.path.join(os.getcwd(), "app.db")

from supabase import create_client, Client

SUPABASE_URL = "https://izzsjvislssztiwtfvut.supabase.co"
SUPABASE_KEY = "sb_publishable_q0XHRgM2feTGxrVLfpOH-w_u7_4soSX"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

IMAGE_FOLDER = "static/images"

if not os.path.exists(IMAGE_FOLDER):
    os.makedirs(IMAGE_FOLDER)

import cloudinary
import cloudinary.uploader

cloudinary.config(
    cloud_name="dgo1mpjup",
    api_key="244212835868316",
    api_secret="nYLo5pZ6ZGjew7IcWi1uC_-QudA"
)



app = Flask(__name__)
app.secret_key = "my_random_stock_secret_key_9876"
UPLOAD_FOLDER = "uploads"
LATEST_FILE = os.path.join(UPLOAD_FOLDER, "latest.csv")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS image_map (
            item_name TEXT PRIMARY KEY,
            image_url TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()

IMAGE_MAP_FILE = "image_map.json"

def load_image_map():
    try:
        # Try fetching from Supabase
        response = supabase.table("image_map").select("*").execute()
        data = response.data
        image_map = {row["item_name"]: row["image_url"] for row in data}
        
        # Save a fresh local backup copy
        with open(IMAGE_MAP_FILE, "w") as f:
            json.dump(image_map, f)
            
        return image_map
    except Exception as e:
        app.logger.error(f"Supabase unreachable, using local fallback: {e}")
        
        # Fallback to local json file if Supabase is offline
        if os.path.exists(IMAGE_MAP_FILE):
            with open(IMAGE_MAP_FILE, "r") as f:
                return json.load(f)
        return {}

def save_image(item_name, image_url):
    # 1. Update local backup file immediately
    image_map = {}
    if os.path.exists(IMAGE_MAP_FILE):
        with open(IMAGE_MAP_FILE, "r") as f:
            image_map = json.load(f)
            
    image_map[item_name] = image_url
    with open(IMAGE_MAP_FILE, "w") as f:
        json.dump(image_map, f)

    # 2. Try syncing to Supabase in the background
    try:
        supabase.table("image_map").upsert({
            "item_name": item_name,
            "image_url": image_url
        }).execute()
    except Exception as e:
        app.logger.error(f"Failed to sync image to Supabase (saved locally instead): {e}")

@app.route("/", methods=["GET", "POST"])
def index():
    search = request.args.get("search", "").lower()
    data = []

    # ✅ HANDLE NEW UPLOAD
    if request.method == "POST":
        file = request.files.get("file")

        if file:
            file.save(LATEST_FILE)   # overwrite old file
            return redirect("/")    # reload page

    # ✅ LOAD LAST UPLOADED FILE
    if os.path.exists(LATEST_FILE):
        df = process_data(LATEST_FILE)

        image_map = load_image_map()

        df["image"] = df["item_name"].map(image_map).fillna("")

        # Filter
        if search:
            if search.isdigit():
                val = int(search)

                min_val = int(val * 0.7)   # -30%
                max_val = int(val * 1.3)   # +30%

                df = df[(df['quantity'] >= min_val) & (df['quantity'] <= max_val)]
            else:
                df = df[df['item_name'].fillna("").str.lower().str.contains(search)]

        data = df.to_dict(orient="records")

    return render_template("index.html", items=data, search=search)

@app.route("/upload_image", methods=["POST"])
def upload_image():
    file = request.files.get("image")
    item_name = request.form.get("item_name")

    if file and item_name:
        result = cloudinary.uploader.upload(file)
        image_url = result["secure_url"]

        # 🔥 SAVE MAPPING
        save_image(item_name, image_url)

        return {"url": image_url}

    return {"error": "Upload failed"}, 400

def process_data(filepath):
    df = pd.read_csv(filepath)

    # 1. Normalize column names (strip spaces and lowercase everything)
    df.columns = [str(col).strip().lower() for col in df.columns]

    # 2. Safely find or map the item name column
    if 'item_name' not in df.columns:
        for alt in ['item', 'name', 'product', 'product name']:
            if alt in df.columns:
                df = df.rename(columns={alt: 'item_name'})
                break
        else:
            if len(df.columns) > 0:
                df = df.rename(columns={df.columns[0]: 'item_name'})
            else:
                df['item_name'] = []

    # 3. Safely find or map the quantity column
    if 'quantity' not in df.columns:
        for alt in ['qty', 'stock', 'amount', 'count']:
            if alt in df.columns:
                df = df.rename(columns={alt: 'quantity'})
                break
        else:
            df['quantity'] = 0

    # Convert quantity to numeric safely
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)

    # Load Cloudinary image map (with fallback)
    image_map = load_image_map()

    # Attach image from map
    df['image'] = df['item_name'].fillna("").map(image_map).fillna("")

    # Calculations
    df['extra_30'] = (df['quantity'] * 0.30).astype(int)
    df['final_stock'] = df['quantity'] + df['extra_30']

    # Status
    def stock_status(qty):
        if qty <= 10:
            return "low"
        elif qty >= 100:
            return "high"
        else:
            return "medium"

    df['status'] = df['quantity'].apply(stock_status)

    return df

@app.route("/image-map", methods=["GET"])
def view_image_map():
    return jsonify(load_image_map())

def keep_supabase_alive():
    """Ping Supabase every 3 days to prevent pausing"""
    while True:
        try:
            supabase.table("image_map").select("count").limit(1).execute()
            app.logger.info("Supabase keep-alive ping sent")
        except Exception as e:
            app.logger.error(f"Keep-alive ping failed: {e}")
        
        time.sleep(3 * 24 * 60 * 60)  # Every 3 days


@app.route("/add_item", methods=["POST"])
def add_item():
    item_name = request.form.get("item_name")
    quantity = request.form.get("quantity", 0)
    file = request.files.get("image")

    if item_name:
        image_url = ""
        if file:
            try:
                result = cloudinary.uploader.upload(file)
                image_url = result["secure_url"]
                save_image(item_name, image_url)
            except Exception as e:
                error_str = str(e)
                app.logger.error(f"Cloudinary upload failed: {error_str}")
                
                # Check for file size error specifically
                if "File size too large" in error_str:
                    flash("⚠️ Upload Failed: The image is too large (Maximum size is 10MB). Please choose a smaller photo.", "error")
                else:
                    flash(f"⚠️ Upload Failed: {error_str}", "error")

        # Save or update product in the active CSV file
        if os.path.exists(LATEST_FILE):
            df = pd.read_csv(LATEST_FILE)
            if item_name in df['item_name'].values:
                df.loc[df['item_name'] == item_name, 'quantity'] = quantity
            else:
                new_row = pd.DataFrame([{"item_name": item_name, "quantity": quantity}])
                df = pd.concat([df, new_row], ignore_index=True)
            df.to_csv(LATEST_FILE, index=False)
        else:
            df = pd.DataFrame([{"item_name": item_name, "quantity": quantity}])
            df.to_csv(LATEST_FILE, index=False)

    return redirect("/")


@app.route("/update_quantity", methods=["POST"])
def update_quantity():
    item_name = request.form.get("item_name")
    new_quantity = request.form.get("quantity", 0)

    if item_name and os.path.exists(LATEST_FILE):
        df = pd.read_csv(LATEST_FILE)
        if item_name in df['item_name'].values:
            df.loc[df['item_name'] == item_name, 'quantity'] = pd.to_numeric(new_quantity, errors='coerce')
            df.to_csv(LATEST_FILE, index=False)
            flash(f"✅ Updated quantity for '{item_name}'.", "success")

    return redirect("/")

@app.route("/delete_item", methods=["POST"])
def delete_item():
    item_name = request.form.get("item_name")

    if item_name and os.path.exists(LATEST_FILE):
        df = pd.read_csv(LATEST_FILE)
        # Filter out the item to delete it
        df = df[df['item_name'] != item_name]
        df.to_csv(LATEST_FILE, index=False)
        flash(f"🗑️ Deleted record '{item_name}'.", "success")

    return redirect("/")


# Start background thread when app starts
thread = threading.Thread(target=keep_supabase_alive, daemon=True)
thread.start()

@app.route("/cron")
def cron():
    try:
        data = supabase.table("image_map").select("item_name").limit(1).execute()
        return "Supabase Active ✅"
    except Exception as e:
        return f"Error: {str(e)}"
    

if __name__ == "__main__":
    init_db()
    app.run()

from flask import Flask, render_template, request, redirect
import pandas as pd
import os
from flask import jsonify
import threading
import time
import json
import sqlite3
DB_FILE = os.path.join(os.getcwd(), "app.db")

from supabase import create_client, Client


SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SECRET_KEY"]


supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

IMAGE_FOLDER = "static/images"

if not os.path.exists(IMAGE_FOLDER):
    os.makedirs(IMAGE_FOLDER)

import cloudinary
import cloudinary.uploader

cloudinary.config(
    cloud_name="dgo1mpjup",
    api_key="244212835868316",
    api_secret="nYLo5pZ6ZGjew7IcWi1uC_-QudA"
)



app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
LATEST_FILE = os.path.join(UPLOAD_FOLDER, "latest.csv")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS image_map (
            item_name TEXT PRIMARY KEY,
            image_url TEXT
        )
    """)

    conn.commit()
    conn.close()

init_db()


def load_image_map():
    response = supabase.table("image_map").select("*").execute()

    data = response.data

    return {row["item_name"]: row["image_url"] for row in data}

def save_image(item_name, image_url):
    supabase.table("image_map").upsert({
        "item_name": item_name,
        "image_url": image_url
    }).execute()
    

@app.route("/", methods=["GET", "POST"])
def index():
    search = request.args.get("search", "").lower()
    data = []

    # ✅ HANDLE NEW UPLOAD
    if request.method == "POST":
        file = request.files.get("file")

        if file:
            file.save(LATEST_FILE)   # overwrite old file
            return redirect("/")    # reload page

    # ✅ LOAD LAST UPLOADED FILE
    if os.path.exists(LATEST_FILE):
        df = process_data(LATEST_FILE)

        image_map = load_image_map()

        df["image"] = df["item_name"].map(image_map).fillna("")

        # Filter
        if search:
            if search.isdigit():
                val = int(search)

                min_val = int(val * 0.7)   # -30%
                max_val = int(val * 1.3)   # +30%

                df = df[(df['quantity'] >= min_val) & (df['quantity'] <= max_val)]
            else:
                df = df[df['item_name'].fillna("").str.lower().str.contains(search)]

        data = df.to_dict(orient="records")

    return render_template("index.html", items=data, search=search)

@app.route("/upload_image", methods=["POST"])
def upload_image():
    file = request.files.get("image")
    item_name = request.form.get("item_name")

    if file and item_name:
        result = cloudinary.uploader.upload(file)
        image_url = result["secure_url"]

        # 🔥 SAVE MAPPING
        save_image(item_name, image_url)

        return {"url": image_url}

    return {"error": "Upload failed"}, 400

def process_data(filepath):
    df = pd.read_csv(filepath)

    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)

    # Load Cloudinary image map
    image_map = load_image_map()

    # Attach image from Cloudinary JSON
    df['image'] = df['item_name'].fillna("").map(image_map).fillna("")

    # Calculations
    df['extra_30'] = (df['quantity'] * 0.30).astype(int)
    df['final_stock'] = df['quantity'] + df['extra_30']

    # Status
    def stock_status(qty):
        if qty <= 10:
            return "low"
        elif qty >= 100:
            return "high"
        else:
            return "medium"

    df['status'] = df['quantity'].apply(stock_status)

    return df

@app.route("/image-map", methods=["GET"])
def view_image_map():
    return jsonify(load_image_map())

def keep_supabase_alive():
    """Ping Supabase every 3 days to prevent pausing"""
    while True:
        try:
            supabase.table("image_map").select("count").limit(1).execute()
            app.logger.info("Supabase keep-alive ping sent")
        except Exception as e:
            app.logger.error(f"Keep-alive ping failed: {e}")
        
        time.sleep(3 * 24 * 60 * 60)  # Every 3 days

# Start background thread when app starts
thread = threading.Thread(target=keep_supabase_alive, daemon=True)
thread.start()

@app.route("/cron")
def cron():
    try:
        data = supabase.table("image_map").select("item_name").limit(1).execute()
        return "Supabase Active ✅"
    except Exception as e:
        return f"Error: {str(e)}"
    

if __name__ == "__main__":
    init_db()
    app.run()
