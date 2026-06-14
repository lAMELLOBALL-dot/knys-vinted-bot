"""
Vinted Bot v2 — Knys VIP
Utilise l'API officieuse de Vinted (bien plus fiable que le scraping HTML)
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import time
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
CORS(app)

MOTS_CLES = [
    "nike air jordan",
    "adidas yeezy",
    "new balance",
    "stone island",
    "palace",
    "supreme",
    "sac louis vuitton",
    "cap vintage",
    "airpods",
]

SEUILS_BONNE_AFFAIRE = {
    "default": 50,
    "jordan": 80,
    "yeezy": 100,
    "louis vuitton": 150,
    "airpods": 60,
}

INTERVALLE_SCRAPING_MINUTES = 10

annonces_store = {}
bonnes_affaires = []
ids_vus = set()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}

def get_session_cookie():
    """Récupère un cookie de session Vinted."""
    try:
        s = requests.Session()
        s.get("https://www.vinted.fr", headers=HEADERS, timeout=10)
        return s
    except:
        return requests.Session()

session = get_session_cookie()

def get_seuil(titre):
    titre_lower = titre.lower()
    for mot, seuil in SEUILS_BONNE_AFFAIRE.items():
        if mot in titre_lower:
            return seuil
    return SEUILS_BONNE_AFFAIRE["default"]

def scrape_vinted(mot_cle):
    resultats = []
    try:
        url = "https://www.vinted.fr/api/v2/catalog/items"
        params = {
            "search_text": mot_cle,
            "order": "newest_first",
            "per_page": 20,
        }
        resp = session.get(url, headers=HEADERS, params=params, timeout=15)
        
        if resp.status_code == 401 or resp.status_code == 403:
            # Renouvelle la session
            global session
            session = get_session_cookie()
            resp = session.get(url, headers=HEADERS, params=params, timeout=15)

        if resp.status_code != 200:
            print(f"[{mot_cle}] Erreur {resp.status_code}")
            return []

        data = resp.json()
        items = data.get("items", [])

        for item in items:
            try:
                prix = float(item.get("price", 0))
                photo = item.get("photo", {})
                image_url = photo.get("url", "") if photo else ""
                
                resultats.append({
                    "id": str(item["id"]),
                    "titre": item.get("title", ""),
                    "prix": prix,
                    "taille": item.get("size_title", ""),
                    "marque": item.get("brand_title", ""),
                    "etat": item.get("status", ""),
                    "image": image_url,
                    "lien": f"https://www.vinted.fr/items/{item['id']}",
                    "date": item.get("created_at_ts", int(time.time())),
                    "vendeur": item.get("user", {}).get("login", ""),
                    "bonne_affaire": False,
                    "mot_cle": mot_cle,
                })
            except (KeyError, TypeError, ValueError):
                continue

    except Exception as e:
        print(f"[{mot_cle}] Erreur : {e}")

    return resultats

def run_scraping():
    global bonnes_affaires
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scraping...")
    nouvelles = 0
    bonnes_affaires_temp = []

    for mot in MOTS_CLES:
        items = scrape_vinted(mot)
        for item in items:
            if item["id"] not in ids_vus:
                ids_vus.add(item["id"])
                seuil = get_seuil(item["titre"])
                if item["prix"] > 0 and item["prix"] <= seuil:
                    item["bonne_affaire"] = True
                    item["seuil"] = seuil
                annonces_store[item["id"]] = item
                if item["bonne_affaire"]:
                    bonnes_affaires_temp.append(item)
                nouvelles += 1
        time.sleep(2)

    bonnes_affaires = sorted(bonnes_affaires_temp, key=lambda x: x["date"], reverse=True)[:50]
    print(f"  → {nouvelles} nouvelles | {len(bonnes_affaires)} bonnes affaires")

@app.route("/api/annonces")
def get_annonces():
    mot_cle = request.args.get("q", "").lower()
    limit = int(request.args.get("limit", 50))
    prix_max = request.args.get("prix_max")
    annonces = list(annonces_store.values())
    if mot_cle:
        annonces = [a for a in annonces if mot_cle in a["titre"].lower() or mot_cle in a["marque"].lower()]
    if prix_max:
        annonces = [a for a in annonces if a["prix"] <= float(prix_max)]
    annonces = sorted(annonces, key=lambda x: x["date"], reverse=True)[:limit]
    return jsonify({"annonces": annonces, "total": len(annonces)})

@app.route("/api/bonnes-affaires")
def get_bonnes_affaires():
    return jsonify({"annonces": bonnes_affaires[:20], "total": len(bonnes_affaires)})

@app.route("/api/stats")
def get_stats():
    return jsonify({
        "total_annonces": len(annonces_store),
        "bonnes_affaires": len(bonnes_affaires),
        "mots_cles": MOTS_CLES,
        "derniere_maj": datetime.now().isoformat(),
    })

@app.route("/api/refresh")
def manual_refresh():
    run_scraping()
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    print("Knys VIP — Vinted Bot v2")
    run_scraping()
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_scraping, "interval", minutes=INTERVALLE_SCRAPING_MINUTES)
    scheduler.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
