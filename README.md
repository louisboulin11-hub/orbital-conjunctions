# Orbital Conjunctions

Outil Python qui détecte les rapprochements dangereux entre satellites et débris en orbite
basse, à partir de vraies données publiques, et qui a été validé sur deux collisions réelles.

Sur une journée type, il analyse **~17 800 objets** (soit ~159 millions de paires possibles)
et trouve **~60 000 rapprochements à moins de 5 km**, dont ~2 000 impliquent un débris.

## Fonctionnement

1. **Données** : téléchargement des TLE (*Two-Line Elements*, paramètres d'orbite publiés
   par le NORAD) depuis [CelesTrak](https://celestrak.org), mis en cache 2 h pour respecter
   les règles d'usage du site.
2. **Propagation** : calcul des positions avec l'algorithme **SGP4**, vectorisé
   (154 millions de positions sur 24 h) et découpé en tranches de 30 min pour tenir en mémoire.
3. **Détection en entonnoir** :

   | Étape | Paires restantes |
   |---|---|
   | Toutes les paires possibles | ~159 000 000 |
   | **KD-tree** à chaque instant (pas de 10 s) : paires à moins de 85 km | ~3 700 000 |
   | **Estimation en ligne droite** entre deux instants : paires à moins de 6 km | ~71 000 |
   | **Raffinement** (méthode de Brent, précision 1 ms) : distance exacte < 5 km | ~60 000 événements |

   Le rayon de 85 km garantit de ne rater aucun rapprochement : deux objets en orbite
   basse se croisent à 16 km/s au plus, et le rapprochement maximal tombe à 5 s au plus
   d'un instant de la grille (5 km + 16 km/s × 5 s = 85 km).
   Les objets qui voyagent ensemble (modules amarrés aux stations, vol en formation,
   vitesse relative < 10 m/s) sont écartés.
4. **Restitution** : tableau des rapprochements (avec l'âge des TLE), export CSV, et vues 3D
   interactives (plotly) : la Terre et tous les objets, et le détail d'un croisement.

## Rétro-validation sur des collisions réelles

`backtest.py` rejoue la détection avec les TLE historiques publiés **avant** deux collisions
réelles (source : [Space-Track.org](https://www.space-track.org)), pour vérifier que le
danger aurait été signalé :

| Collision | Information disponible | Distance prévue | Instant prévu | Alerte < 5 km |
|---|---|---|---|---|
| Iridium 33 / Cosmos 2251 (10/02/2009) | de J-3 à quelques heures avant | 584 à 1 039 m | à 0,1 s de l'impact réel | Oui, à chaque fois |
| CERISE / fragment d'Ariane 1 (24/07/1996) | de J-3 à la veille | 895 à 1 168 m | 09:48:02 UTC (heure réelle non publiée) | Oui, à chaque fois |

- Avec les TLE de la veille, l'outil prévoit **584 m** pour Iridium / Cosmos : exactement la
  valeur publiée par le système SOCRATES de CelesTrak le jour de la collision, ce qui valide
  l'ensemble du calcul par une source indépendante.
- La vraie distance était **0 m** : l'écart de 0,6 à 1,2 km illustre l'imprécision des TLE,
  et justifie un seuil d'alerte large (avec un seuil à 1 km, l'alerte aurait été manquée à J-2).
- Seule la paire concernée a été rejouée : ce test valide la **détection**, pas la
  **priorisation**. En 2009, SOCRATES avait signalé ce rapprochement, mais parmi des
  centaines d'autres (64ᵉ en moyenne) : sans probabilité de collision, impossible de
  distinguer le vrai danger.

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows (macOS / Linux : source .venv/bin/activate)
pip install -r requirements.txt
```

## Utilisation

| Commande | Rôle | Durée |
|---|---|---|
| `python main.py` | Détection des rapprochements sur les prochaines 24 h, résultats enregistrés dans `output/` | ~6 min |
| `python view.py` | Vues 3D à jour (positions actuelles, rapprochements à venir) à partir de la dernière détection | ~3 s |
| `python backtest.py` | Rétro-validation sur les collisions de 2009 et 1996 | ~4 s |
| `python demo.py` | Démonstration pas à pas : TLE décodé, position de l'ISS, répartition des altitudes | quelques s |

Principales options (liste complète avec `--help`) :

```bash
python main.py --threshold 1           # seuil d'alerte à 1 km (défaut : 5 km)
python main.py --hours 12              # fenêtre de prédiction de 12 h (défaut : 24 h)
python main.py --debris-only           # n'afficher que les rapprochements impliquant un débris
python main.py --csv output/events.csv # exporter les rapprochements affichés

python view.py --debris-only           # vues 3D limitées aux rapprochements impliquant un débris
python view.py --event 3               # détailler le 3ᵉ rapprochement à venir
```

La détection, longue, ne se relance qu'une ou deux fois par jour ; `view.py` donne ensuite
des vues à jour en quelques secondes (il suffit de rafraîchir la page HTML).

`backtest.py` demande des identifiants Space-Track (compte gratuit) au premier lancement :
le mot de passe est saisi de façon invisible et n'est jamais enregistré. Les données
téléchargées restent dans `data/history/` (les conditions d'utilisation de Space-Track
interdisent de les redistribuer).

## Structure du projet

```
main.py                   détection (point d'entrée principal)
view.py                   vues 3D à partir de la dernière détection
backtest.py               rétro-validation sur des collisions réelles
demo.py                   démonstration des briques de base
conjunctions/
    fetch.py              téléchargement des TLE (CelesTrak) et des côtes, avec cache
    catalog.py            lecture des TLE, catalogue d'objets, filtre orbite basse
    propagate.py          SGP4, propagation vectorisée, conversion en latitude / longitude
    screening.py          détection en entonnoir (KD-tree, ligne droite, raffinement)
    report.py             tableaux, export CSV, enregistrement des résultats
    visualize.py          vues 3D (plotly)
    history.py            TLE historiques (Space-Track)
```

## Limites

- **Précision des TLE** : ~1 km au moment de la mesure, et l'erreur croît de quelques km par
  jour. Les distances affichées sont des distances *nominales* : l'outil fait du
  **criblage** (repérer les rapprochements qui méritent une analyse fine), pas du calcul de
  probabilité de collision, qui nécessiterait l'incertitude de chaque position.
- **Manœuvres** : un satellite qui allume ses moteurs rend ses TLE caducs jusqu'à la mesure
  suivante. Or les satellites Starlink, qui manœuvrent de façon autonome, sont en cause dans
  la grande majorité des rapprochements détectés (~78 % se produisent entre deux Starlink).
- **Priorisation** : les rapprochements sont classés par distance nominale, qui n'est pas
  un indicateur de danger fiable (voir la rétro-validation).

## Pistes d'amélioration écartées

Identifiées, puis volontairement non réalisées car leur coût dépassait leur apport :

- **Paralléliser la détection** sur plusieurs cœurs : les instants de la grille sont
  indépendants, le calcul se répartirait bien, mais la détection ne tourne qu'une ou deux
  fois par jour.
- **Positions en temps réel dans la page** : soit un petit serveur web local, soit SGP4
  exécuté dans le navigateur (JavaScript, satellite.js). `view.py` en 3 s suffit.
- **Animation** des objets : surtout décorative, pour une page 5 à 10 fois plus lourde.
- **Rejouer le catalogue complet de 2009** : permettrait de tester la priorisation, et plus
  seulement la détection.
