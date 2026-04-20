from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
from collections import defaultdict
import time
import os
import json

app = Flask(__name__)

# =========================
# 🔐 FIREBASE INIT (REPLIT SECRETS)
# =========================
# Put your Firebase service account JSON in Replit Secrets as:
# KEY: FIREBASE_CREDENTIALS
# VALUE: (paste full JSON)

firebase_json = os.environ.get("FIREBASE_CREDENTIALS")

if not firebase_json:
    raise Exception("FIREBASE_CREDENTIALS not found in environment variables")

cred_dict = json.loads(firebase_json)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

# =========================
# 🔹 MODEL FUNCTIONS
# =========================

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


build_model()


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
    score = round(final*100, 2)

    if score >= 75:
        status = "High"
    elif score >= 50:
        status = "Medium"
    elif score >= 25:
        status = "Low"
    else:
        status = "Very Low"

    return score, status


def retrain_model():
    build_model()


def extract_number(bond_id):
    return int(str(bond_id).split("-")[-1])


def clean_denomination(value):
    return str(value).replace("Rs.", "").replace("Rs", "").replace(".", "").strip()

# =========================
# 🔹 CORE FUNCTIONS
# =========================

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

        return {"bond": bond_id, "probability": prob, "status": status}

    except Exception as e:
        return {"error": str(e)}


def recommend_bonds(budget):
    try:
        budget = int(budget)

        bond_values = [100, 200, 750, 1500]
        plans = []

        p1_count = budget // 100
        p1_total = p1_count * 100

        plans.append({
            "plan": "Plan 1 - Maximum Bonds",
            "details": [{"bond_value": 100, "quantity": p1_count, "total_cost": p1_total}],
            "remaining": budget - p1_total
        })

        return {"budget": budget, "plans": plans}

    except Exception as e:
        return {"error": str(e)}


def update_all_users_bonds():
    try:
        users_ref = db.collection("artifacts")\
            .document("default-app-id")\
            .collection("users")\
            .stream()

        total_users = 0
        total_bonds = 0

        for user in users_ref:
            user_id = user.id
            total_users += 1

            bonds_ref = db.collection("artifacts")\
                .document("default-app-id")\
                .collection("users")\
                .document(user_id)\
                .collection("bonds")\
                .stream()

            for bond in bonds_ref:
                data = bond.to_dict()
                bond_id = data.get("number", "")

                if not bond_id:
                    continue

                bond_number = extract_number(bond_id)
                prob, status = calculate_probability(bond_number)

                bond.reference.set({
                    "cleanNumber": str(bond_number),
                    "probability": prob,
                    "status": status,
                    "updatedAt": int(time.time())
                }, merge=True)

                total_bonds += 1

        return {"status": "Updated", "users": total_users, "bonds": total_bonds}

    except Exception as e:
        return {"error": str(e)}


def check_all_winners():

    try:
        users_ref = db.collection("artifacts")\
            .document("default-app-id")\
            .collection("users")\
            .stream()

        total_winners = 0

        for user in users_ref:

            user_id = user.id

            bonds_ref = db.collection("artifacts")\
                .document("default-app-id")\
                .collection("users")\
                .document(user_id)\
                .collection("bonds")\
                .stream()

            for bond in bonds_ref:

                data = bond.to_dict()
                bond_id = data.get("number", "")
                denomination = data.get("denomination", "")

                if not bond_id:
                    continue

                bond_number = str(extract_number(bond_id))
                clean_denom = clean_denomination(denomination)

                docs = db.collection("draw_results").stream()

                for doc in docs:

                    draw = doc.to_dict()
                    draw_denom = clean_denomination(draw.get("category", ""))

                    numbers = draw.get("numbers", [])
                    date = draw.get("date", "")

                    if clean_denom != draw_denom:
                        continue

                    for idx, num in enumerate(numbers):

                        try:
                            num = str(num)
                        except:
                            continue

                        if num.zfill(6) == bond_number.zfill(6):

                            position = 1 if idx == 0 else 2 if idx <= 3 else 3

                            db.collection("artifacts")\
                                .document("default-app-id")\
                                .collection("users")\
                                .document(user_id)\
                                .collection("notifications")\
                                .add({
                                    "title": "🎉 Congratulations!",
                                    "message": f"🎉 Your Bond {bond_id} (Rs {clean_denom}) won {position} Prize 🏆",
                                    "bond": bond_id,
                                    "denomination": clean_denom,
                                    "position": position,
                                    "date": date,
                                    "type": "winner",
                                    "createdAt": int(time.time())
                                })

                            total_winners += 1
                            break

        return {
            "status": "Winner Check Completed",
            "winners_found": total_winners
        }

    except Exception as e:
        return {"error": str(e)}

# =========================
# 🔥 ROUTES
# =========================

@app.route("/")
def home():
    return "API Running 🚀"


@app.route("/probability", methods=["POST"])
def probability():
    data = request.json
    score, status = calculate_probability(int(data.get("number")))
    return jsonify({"score": score, "status": status})


@app.route("/add-bond", methods=["POST"])
def add_bond():
    data = request.json
    return jsonify(add_bond_with_dataset_check(data["user_id"], data["bond_id"], data["denomination"]))


@app.route("/recommend", methods=["POST"])
def recommend():
    data = request.json
    return jsonify(recommend_bonds(data["budget"]))


@app.route("/update-all", methods=["GET"])
def update_all():
    return jsonify(update_all_users_bonds())


@app.route("/retrain", methods=["GET"])
def retrain():
    retrain_model()
    return jsonify({"status": "Model retrained"})


@app.route("/check-winners", methods=["GET"])
def winners():
    return jsonify(check_all_winners())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
