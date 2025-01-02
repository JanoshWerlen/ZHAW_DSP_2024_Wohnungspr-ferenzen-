from flask import Flask, request, render_template, jsonify
import pandas as pd
import sqlite3
import os

def format_duration(duration):
    """
    Convert HH:MM duration into total minutes. If already an integer, return as is.
    """
    if isinstance(duration, int):  # If duration is already an integer, return it
        return duration
    try:
        hours, minutes = map(int, duration.split(":"))
        return hours * 60 + minutes
    except ValueError:
        return 0  # Default to 0 for invalid formats


def load_coordinates_from_db(maxprice=None, root_property_type=None, max_duration=None, university_filter=None, max_transfers=None):
    conn = sqlite3.connect("locations.db")
    
    # Dynamically construct the listings columns
    listings_column = None
    if maxprice is not None and root_property_type is not None:
        listings_column = f"listings_{maxprice}_type_{root_property_type}"
    elif maxprice is not None:
        listings_column = f"listings_{maxprice}_type_1 + listings_{maxprice}_type_3"

    # Build the base query
    query = """
    SELECT 
        coordinate_x AS latitude, 
        coordinate_y AS longitude, 
        from_station AS tag, 
        plz, 
        min_duration as duration, 
        university, 
        transfers
    """
    if listings_column:
        query += f", {listings_column} AS filtered_listings_WG"
    else:
        query += ", 0 AS filtered_listings_WG"
    
    query += """
    FROM master_table
    WHERE duration IS NOT 'No connection'
    """

    # Load data into a DataFrame
    data = pd.read_sql_query(query, conn)
    conn.close()

    # Replace missing values with defaults
    data.fillna({'duration': '00:00', 'filtered_listings_WG': 0, 'university': 'Unknown', 'transfers': 0}, inplace=True)

    # Apply filters dynamically
    data["duration_minutes"] = data["duration"].apply(format_duration)
    if max_duration is not None:
        data = data[data["duration_minutes"] <= max_duration]
    if university_filter:
        data = data[data["university"] == university_filter]
    if max_transfers is not None:
        data = data[data["transfers"] <= max_transfers]

    return data

def get_unique_universities():
    conn = sqlite3.connect("locations.db")
    query = "SELECT DISTINCT university FROM master_table WHERE university IS NOT NULL AND university != ''"
    universities = pd.read_sql_query(query, conn)["university"].tolist()
    conn.close()
    return universities

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("map.html")

@app.route("/filter", methods=["GET"])
def filter_data():
    maxprice = request.args.get("maxprice", None, type=int)
    root_property_type = request.args.get("property_type", None, type=int)
    max_duration = request.args.get("duration", None, type=int)
    university = request.args.get("university", None)
    max_transfers = request.args.get("transfers", None, type=int)

    # Fetch filtered data
    data = load_coordinates_from_db(
        maxprice=maxprice,
        root_property_type=root_property_type,
        max_duration=max_duration,
        university_filter=university,
        max_transfers=max_transfers
    )

    # Group by PLZ and calculate total listings, include to_station
    plz_listings = (
        data.groupby(["plz", "tag"])["filtered_listings_WG"]
        .sum()
        .reset_index()
        .rename(columns={"filtered_listings_WG": "total_listings", "tag": "ort"})
        .sort_values(by="total_listings", ascending=False)
    )

    # Convert to dictionary format for JSON response
    plz_listings = plz_listings[plz_listings["total_listings"] > 0].to_dict(orient="records")

    features = []
    for _, row in data.iterrows():
        if root_property_type and row["filtered_listings_WG"] == 0:
            marker_color = "red"
        elif row["filtered_listings_WG"] > 0:
            marker_color = "blue"
        else:
            marker_color = "green"  # Combined results

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row["longitude"], row["latitude"]],
            },
            "properties": {
                "tag": row["tag"],
                "plz": row["plz"],
                "duration": row["duration"],
                "filtered_listings_WG": row["filtered_listings_WG"],
                "university": row["university"],
                "transfers": row["transfers"],
                "marker_color": marker_color,
                "property_type": "Wohnung" if root_property_type == 1 else "WG-Zimmer" if root_property_type == 3 else "Mixed"
            },
        }
        features.append(feature)

    return jsonify({
        "map_data": {"type": "FeatureCollection", "features": features},
        "plz_listings": plz_listings
    })



@app.route("/universities", methods=["GET"])
def get_universities():
    universities = get_unique_universities()
    return jsonify(universities)

if __name__ == "__main__":
    if not os.path.exists("templates"):
        os.makedirs("templates")
    app.run(debug=True)
