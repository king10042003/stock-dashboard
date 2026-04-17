from flask import Flask, render_template, request, redirect
import pandas as pd
import os
from flask import jsonify
import json

IMAGE_MAP_FILE = "image_map.json"

def load_image_map():
    if os.path.exists(IMAGE_MAP_FILE):
        with open(IMAGE_MAP_FILE, "r") as f:
            return json.load(f)
    return {}

def save_image_map(data):
    with open(IMAGE_MAP_FILE, "w") as f:
        json.dump(data, f)

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
                df = df[df['item_name'].str.lower().str.contains(search)]

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
        image_map = load_image_map()
        image_map[item_name] = image_url
        save_image_map(image_map)

        return {"url": image_url}

    return {"error": "Upload failed"}, 400

def process_data(filepath):
    df = pd.read_csv(filepath)

    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)

    # Load Cloudinary image map
    image_map = load_image_map()

    # Attach image from Cloudinary JSON
    df['image'] = df['item_name'].map(image_map).fillna("")

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
    
if __name__ == "__main__":
    app.run()
