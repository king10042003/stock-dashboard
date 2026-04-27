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
