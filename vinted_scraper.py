from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import time
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
CORS(app)

SCRAPER_API_KEY = "7c1162adb095c7d643a96b4208f634d1"

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

INTERVALLE_SCRAPING_MINUTES = 500

annonces_store = {}
bonnes_affaires = []
ids_vus = set()

def get_seuil(titre):
    titre_lower = titre.lower()
    for mot, seuil in SEUILS_BONNE_AFFAIRE.items():
        if mot in titre_lower:
            return seuil
    return SEUILS_BONNE_AFFAIRE["default"]

def scrape_vinted(mot_cle):
    resultats = []
    try:
        target_url = f"https://www.vinted.fr/api/v2/catalog/items?search_text={requests.utils.quote(mot_cle)}&order=newest_first&per_page=20"
        
        payload = {
            "api_key": SCRAPER_API_KEY,
            "url": target_url,
            "country_code": "fr",
            "render": "false",
        }
        
        resp = requests.get("https://api.scraperapi.com/", params=payload, timeout=60)
        print(f"[{mot_cle}] Status: {resp.status_code}")

        if resp.status_code != 200:
            print(f"[{mot_cle}] Echec: {resp.text[:200]}")
            return []

        data = resp.json()
        items = data.get("items", [])
        print(f"[{mot_cle}] {len(items)} items trouvés")

        for item in items:
            try:
                prix_data = item.get("price", {})
                prix = float(prix_data.get("amount", 0)) if isinstance(prix_data, dict) else float(prix_data or 0)
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
            except (KeyError, TypeError, ValueError) as e:
                print(f"Erreur item: {e}")
                continue

    except Exception as e:
        print(f"[{mot_cle}] Exception: {e}")

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
    print(f"  -> {nouvelles} nouvelles | {len(bonnes_affaires)} bonnes affaires")

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
    print("Knys VIP - Vinted Bot v5")
    run_scraping()
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_scraping, "interval", minutes=INTERVALLE_SCRAPING_MINUTES)
    scheduler.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
