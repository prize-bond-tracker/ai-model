from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
from collections import defaultdict
import os, json, time

# 🔷 FIREBASE (SECRET)
firebase_json = os.environ.get("FIREBASE_KEY")
cred_dict = json.loads(firebase_json)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

# 🔷 LOAD DATASET
def load_dataset():
    docs = db.collection("draw_results").stream()
    dataset = []

    for doc in docs:
        data = doc.to_dict()
        numbers = data.get("numbers", [])

        for idx, num in enumerate(numbers):
            try:
                num = int(num)
            except:
                continue

            if idx == 0:
                position = 1
            elif idx <= 3:
                position = 2
            else:
                position = 3

            dataset.append({
                "number": num,
                "position": position
            })

    return dataset

# 🔷 BUILD MODEL
def build_model():
    global DATASET, number_stats, TOTAL_ENTRIES

    DATASET = load_dataset()
    number_stats = defaultdict(list)

    for i, item in enumerate(DATASET):
        number_stats[item["number"]].append({
            "index": i,
            "position": item["position"]
        })

    TOTAL_ENTRIES = len(DATASET)

# 🔷 PROBABILITY
def calculate_probability(bond_number):

    occurrences = number_stats.get(bond_number, [])
    win_count = len(occurrences)

    freq_score = 1/(win_count+1) if win_count else 1

    if win_count:
        last_index = occurrences[-1]["index"]
        recency_score = (TOTAL_ENTRIES - last_index) / TOTAL_ENTRIES
    else:
        recency_score = 1

    position_score = 0
    for o in occurrences:
        if o["position"] == 1:
            position_score += 1
        elif o["position"] == 2:
            position_score += 0.6
        else:
            position_score += 0.2

    position_score = position_score / win_count if win_count else 0.5

    final = (0.4*freq_score)+(0.4*recency_score)+(0.2*position_score)
    score = round(final*100,2)

    if score >= 75:
        status = "High"
    elif score >= 50:
        status = "Medium"
    elif score >= 25:
        status = "Low"
    else:
        status = "Very Low"

    return score, status

# 🔷 RETRAIN
def retrain_model():
    build_model()

# 🔷 HELPER
def extract_number(bond_id):
    return int(str(bond_id).split("-")[-1])

# 🔷 ADD BOND FUNCTION
def add_bond_with_dataset_check(user_id, bond_id, denomination):

    try:
        bond_id = str(bond_id)
        bond_number = extract_number(bond_id)

        prob, status = calculate_probability(bond_number)

        bonds_ref = db.collection("artifacts")\
            .document("default-app-id")\
            .collection("users")\
            .document(user_id)\
            .collection("bonds")\
            .where("number", "==", bond_id)\
            .stream()

        found = False

        for doc in bonds_ref:
            doc.reference.set({
                "number": bond_id,
                "cleanNumber": str(bond_number),
                "probability": prob,
                "status": status,
                "denomination": denomination,
                "updatedAt": int(time.time())
            }, merge=True)
            found = True
            break

        if not found:
            db.collection("artifacts")\
                .document("default-app-id")\
                .collection("users")\
                .document(user_id)\
                .collection("bonds")\
                .add({
                    "number": bond_id,
                    "cleanNumber": str(bond_number),
                    "probability": prob,
                    "status": status,
                    "denomination": denomination,
                    "createdAt": int(time.time())
                })

        docs = db.collection("draw_results")\
            .where("denomination", "==", str(denomination))\
            .stream()

        wins = []

        for doc in docs:
            data = doc.to_dict()
            numbers = data.get("numbers", [])
            date = data.get("date", "")

            for idx, num in enumerate(numbers):
                try:
                    num = int(num)
                except:
                    continue

                if num == bond_number:
                    position = 1 if idx == 0 else 2 if idx <= 3 else 3

                    wins.append({
                        "date": str(date),
                        "position": position,
                        "denomination": denomination
                    })

        if len(wins) > 0:
            latest = wins[-1]

            db.collection("artifacts")\
                .document("default-app-id")\
                .collection("users")\
                .document(user_id)\
                .collection("notifications")\
                .add({
                    "title": "🎉 Congratulations!",
                    "message": f"Bond {bond_id} won {latest['position']} prize",
                    "bond": bond_id,
                    "position": latest["position"],
                    "createdAt": int(time.time())
                })

        return {
            "bond": bond_id,
            "probability": prob,
            "status": status,
            "total_wins": len(wins),
            "history": wins
        }

    except Exception as e:
        return {"error": str(e)}

# 🔷 RECOMMEND
def recommend_bonds(budget):
    budget = int(budget)
    return {
        "budget": budget,
        "plans": [
            {"bond_value": 100, "quantity": budget//100}
        ]
    }

# 🔷 ADMIN UPDATE
def update_all_users_bonds_with_winner_check():

    users = db.collection("artifacts").document("default-app-id").collection("users").stream()

    for user in users:
        bonds = db.collection("artifacts").document("default-app-id")\
            .collection("users").document(user.id).collection("bonds").stream()

        for bond in bonds:
            data = bond.to_dict()
            bond_id = data.get("number", "")

            if not bond_id:
                continue

            bond_number = extract_number(bond_id)
            prob, status = calculate_probability(bond_number)

            bond.reference.set({
                "probability": prob,
                "status": status,
                "updatedAt": int(time.time())
            }, merge=True)

    return {"status": "updated"}

# 🔷 FLASK
app = Flask(__name__)
CORS(app)

@app.route("/")
def home():
    return "API Running"

@app.route("/addBond", methods=["POST"])
def api_add():
    data = request.json
    return jsonify(add_bond_with_dataset_check(data["userId"], data["bondId"], data["denomination"]))

@app.route("/recommend", methods=["POST"])
def api_rec():
    return jsonify(recommend_bonds(request.json["budget"]))

@app.route("/admin/update", methods=["GET"])
def api_update():
    return jsonify(update_all_users_bonds_with_winner_check())

@app.route("/admin/retrain", methods=["GET"])
def api_retrain():
    retrain_model()
    return jsonify({"status": "retrained"})

if __name__ == "__main__":
    build_model()
    app.run(host="0.0.0.0", port=5000)
