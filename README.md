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

## Statut

En cours de construction, étape par étape.
