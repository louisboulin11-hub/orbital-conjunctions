# Orbital Conjunctions

Outil Python qui détecte les rapprochements dangereux entre satellites et débris en orbite basse, à partir de vraies données publiques.

## Principe

1. **Données** : téléchargement des TLE (Two-Line Elements) depuis [CelesTrak](https://celestrak.org).
2. **Propagation** : calcul des positions futures avec l'algorithme SGP4.
3. **Détection** : recherche des paires d'objets qui passent sous un seuil de distance (en trois filtres successifs).
4. **Restitution** : tableau des événements à risque et visualisation 3D.

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

## Utilisation

```bash
python main.py                         # rapprochements à moins de 5 km sur 24 h
python main.py --threshold 1           # seuil d'alerte à 1 km
python main.py --hours 12              # fenêtre de prédiction de 12 h
python main.py --debris-only           # uniquement ceux qui impliquent un débris
python main.py --csv output/events.csv # export de tous les événements
python main.py --help                  # liste complète des options

python demo.py                         # démonstration : TLE décodé, position de l'ISS...
```

Un calcul complet sur 24 h prend quelques minutes.

## Limites

Les TLE ne sont précis qu'à ~1 km près, et l'erreur croît de quelques km par jour.
Les distances affichées sont donc des distances *nominales* : l'outil fait du
**criblage** (repérer les rapprochements qui méritent une analyse fine), pas du
calcul de probabilité de collision.

## Statut

En cours de construction, étape par étape.
