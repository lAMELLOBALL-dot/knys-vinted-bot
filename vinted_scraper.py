"""
Vinted Bot — Senyou Shop
Scrape les annonces Vinted et expose une API REST pour ton site Lovable.

Prérequis :
  pip install flask flask-cors requests beautifulsoup4 apscheduler

Lancement :
  python vinted_scraper.py

L'API tourne sur http://localhost:5000
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import json
import time
import re
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
CORS(app)  # Autorise les requêtes depuis ton site Lovable

# ─── CONFIG ────────────────────────────────────────────────────────────────────

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

# Prix max pour qu'une annonce soit considérée "bonne affaire"
SEUILS_BONNE_AFFAIRE = {
    "default": 50,      # Si pas de règle spécifique, alerte sous 50€
    "jordan": 80,
    "yeezy": 100,
    "louis vuitton": 150,
    "airpods": 60,
}

INTERVALLE_SCRAPING_MINUTES = 5

# ─── STOCKAGE EN MÉMOIRE ───────────────────────────────────────────────────────

annonces_store = {}       # {id_annonce: annonce_dict}
bonnes_affaires = []      # Liste des annonces sous le seuil de prix
ids_vus = set()           # Pour ne pas rajouter les doublons

# ─── SCRAPER ──────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def get_seuil(titre: str) -> int:
    titre_lower = titre.lower()
    for mot, seuil in SEUILS_BONNE_AFFAIRE.items():
        if mot in titre_lower:
            return seuil
    return SEUILS_BONNE_AFFAIRE["default"]

def scrape_vinted(mot_cle: str) -> list:
    """Scrape les annonces Vinted pour un mot-clé donné."""
    resultats = []
    url = f"https://www.vinted.fr/catalog?search_text={requests.utils.quote(mot_cle)}&order=newest_first"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            print(f"[{mot_cle}] Erreur HTTP {resp.status_code}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")

        # Vinted charge les annonces en JSON dans une balise script
        scripts = soup.find_all("script", type="application/json")
        for script in scripts:
            try:
                data = json.loads(script.string or "")
                # Chercher les items dans la structure JSON de Vinted
                items = _extract_items_from_json(data)
                if items:
                    resultats.extend(items)
                    break
            except (json.JSONDecodeError, TypeError):
                continue

        # Fallback : parsing HTML direct
        if not resultats:
            resultats = _parse_html_items(soup, mot_cle)

    except requests.RequestException as e:
        print(f"[{mot_cle}] Erreur réseau : {e}")

    return resultats

def _extract_items_from_json(data: dict) -> list:
    """Extrait les annonces depuis le JSON embarqué de Vinted."""
    items = []

    def _recurse(obj):
        if isinstance(obj, dict):
            # Structure typique d'un item Vinted
            if "id" in obj and "title" in obj and "price" in obj:
                try:
                    prix = float(str(obj.get("price", {}).get("amount", obj.get("price", 0))))
                    item = {
                        "id": str(obj["id"]),
                        "titre": obj.get("title", ""),
                        "prix": prix,
                        "taille": obj.get("size_title", ""),
                        "marque": obj.get("brand_title", ""),
                        "etat": obj.get("status", ""),
                        "image": _get_image_url(obj),
                        "lien": f"https://www.vinted.fr/items/{obj['id']}",
                        "date": obj.get("created_at_ts", int(time.time())),
                        "vendeur": obj.get("user", {}).get("login", ""),
                        "bonne_affaire": False,
                    }
                    items.append(item)
                except (TypeError, ValueError):
                    pass
            for v in obj.values():
                _recurse(v)
        elif isinstance(obj, list):
            for el in obj:
                _recurse(el)

    _recurse(data)
    return items

def _get_image_url(obj: dict) -> str:
    """Extrait l'URL de la première photo."""
    try:
        photos = obj.get("photos", [])
        if photos:
            return photos[0].get("url", photos[0].get("full_size_url", ""))
        photo = obj.get("photo", {})
        return photo.get("url", photo.get("full_size_url", ""))
    except (IndexError, AttributeError):
        return ""

def _parse_html_items(soup: BeautifulSoup, mot_cle: str) -> list:
    """Fallback : parse le HTML si le JSON n'est pas trouvé."""
    items = []
    cards = soup.select("[data-testid='item-box']") or soup.select(".feed-grid__item")
    for card in cards[:20]:
        try:
            titre_el = card.select_one("[data-testid='description-title']") or card.select_one(".ItemBox_title")
            prix_el = card.select_one("[data-testid='item-box-price-number']") or card.select_one(".ItemBox_price")
            img_el = card.select_one("img")
            lien_el = card.select_one("a")

            if not titre_el or not prix_el:
                continue

            prix_text = re.sub(r"[^\d,.]", "", prix_el.get_text())
            prix = float(prix_text.replace(",", ".")) if prix_text else 0

            item_id = lien_el["href"].split("/")[-1] if lien_el else str(time.time())

            items.append({
                "id": item_id,
                "titre": titre_el.get_text(strip=True),
                "prix": prix,
                "taille": "",
                "marque": mot_cle,
                "etat": "",
                "image": img_el.get("src", img_el.get("data-src", "")) if img_el else "",
                "lien": f"https://www.vinted.fr{lien_el['href']}" if lien_el else "",
                "date": int(time.time()),
                "vendeur": "",
                "bonne_affaire": False,
            })
        except (AttributeError, ValueError, KeyError):
            continue
    return items

# ─── LOGIQUE DE SURVEILLANCE ───────────────────────────────────────────────────

def run_scraping():
    """Lance le scraping de tous les mots-clés."""
    global bonnes_affaires
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scraping en cours...")
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
                item["mot_cle"] = mot
                annonces_store[item["id"]] = item
                if item["bonne_affaire"]:
                    bonnes_affaires_temp.append(item)
                nouvelles += 1
        time.sleep(1.5)  # Pause entre chaque requête

    # Garder les 50 dernières bonnes affaires
    bonnes_affaires = sorted(bonnes_affaires_temp, key=lambda x: x["date"], reverse=True)[:50]
    print(f"  → {nouvelles} nouvelles annonces | {len(bonnes_affaires)} bonnes affaires")

# ─── API ENDPOINTS ─────────────────────────────────────────────────────────────

@app.route("/api/annonces")
def get_annonces():
    """Retourne toutes les annonces (triées par date, les plus récentes en premier)."""
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
    """Retourne uniquement les annonces sous le seuil de prix."""
    return jsonify({"annonces": bonnes_affaires[:20], "total": len(bonnes_affaires)})

@app.route("/api/stats")
def get_stats():
    """Stats globales pour le dashboard."""
    return jsonify({
        "total_annonces": len(annonces_store),
        "bonnes_affaires": len(bonnes_affaires),
        "mots_cles": MOTS_CLES,
        "derniere_maj": datetime.now().isoformat(),
    })

@app.route("/api/refresh")
def manual_refresh():
    """Déclenche un scraping manuel."""
    run_scraping()
    return jsonify({"status": "ok", "message": "Scraping terminé"})

# ─── LANCEMENT ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🔍 Vinted Bot — Senyou Shop")
    print(f"   Mots-clés surveillés : {', '.join(MOTS_CLES)}")
    print(f"   Scraping toutes les {INTERVALLE_SCRAPING_MINUTES} minutes")
    print("   API disponible sur http://localhost:5000\n")

    # Premier scraping au démarrage
    run_scraping()

    # Scheduler pour scraping automatique
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_scraping, "interval", minutes=INTERVALLE_SCRAPING_MINUTES)
    scheduler.start()

    app.run(host="0.0.0.0", port=5000, debug=False)
