# Vérificateur de Buques — Clun'ss (Arts & Métiers)

Application web collaborative (temps réel sur le réseau local) dédiée à la **saisie des feuilles de buques des premières années** et à la **vérification orthographique & phonétique** selon les usages du Tabagn's de Clun'ss.

> Un guide complet rédigé en clun'ssois est également disponible à la racine du dépôt : [`Guide_Protocole_Buques_Clunss.pdf`](./Guide_Protocole_Buques_Clunss.pdf).

---

## 1. Objectif & Règles d'usage

Chaque année, les premières années choisissent leur surnom (**buque**) en rendant une feuille comportant :
- **Recto** : nom de famille et **3 propositions ordonnées** ;
- **Verso** : les **3 polices d'écriture** associées.

L'application évalue automatiquement chaque proposition selon les **4 usages** (en écriture normalisée **et** en phonétique française) et attribue un code couleur par ordre de priorité :

| Priorité | Couleur | Règle | Signification |
| :---: | :--- | :--- | :--- |
| 1 | **Violet** | Règle 2 | Déjà porté ou trop proche d'un surnom de **CT** (Comité des Traditions) |
| 2 | **Rouge** | Règle 1 | Déjà porté ou trop proche d'un PG sur les **10 dernières années** (paramétrable) |
| 3 | **Orange** | Règle 4 | **Référence problématique** (détection automatique via lexique modifiable + signalement manuel) |
| 4 | **Jaune** | Règle 3 | **Ressemblance** dans la **même prom'ss** (avec un autre élève) |
| 5 | **Vert** | — | **Utilisable** (aucun conflit détecté) |

---

## 2. Spécificités phonétiques & notations Clun'ss

Le moteur ([`app/phonetics.py`](app/phonetics.py)) interprète automatiquement les conventions d'écriture :

- **Transposée (`ᵀ`, `ᵗ`, `⊤`, `^T`)** : le mot entre parenthèses ou accolé se lit à l'envers.  
  *Ex. : `(toto)ᵀ = otot`, `ᵀ(mot) = tom`, `GO^t(ARTS) = ogarts`. Un `t` ordinaire sans exposant n'est jamais inversé (`(Arts)tiphi's`, `Cl(Arts)té`).*
- **Puissance 0 (`^0`, `⁰`)** : le segment ne se lit pas.  
  *Ex. : `Super(test)^0 = Super`.*
- **Parenthèses visuelles (`(arts)`, `(art)`, `(...)`)** : génère les lectures orale et littérale.  
  *Ex. : `pompl(arts)` = `pomplar` / `pomplart` / `pomplard` ; `Bas(art)` = `Bazar`.*
- **Carré (`²`, `^2`)** : génère les **deux** lectures possibles :
  1. le mot ou groupe précédent lu **2 fois** (`Bip² = BipBip`, `(BUG)² = Bugbug`, `Paga(ni)² = Paganini`, `(J(arts))² = JarJar`) ;
  2. la lecture **« karse »** (`Mou² = Moukarse` / `Moukars`, `Ba² = Bakarse` / `Bacars`).
- **Symboles & chimie** : `(H2O)` → `o` (`Asph(H2O)dèle`), `π` → `pi` (`πRHANA`), `φ` → `fi`, `Ω` → `o`, `∞` → `oo` (`L∞πng`), `α` → `alfa`, `τ` → `to`, etc.

---

## 3. Installation & lancement

### Prérequis
- **Python 3.10+** (`pip` inclus)

### Installation

```bash
git clone https://github.com/Heorty/verificateur-buques.git
cd verificateur-buques
pip install -r requirements.txt
```

### Démarrage

- **Sous Windows** : double-cliquez sur [`lancer.bat`](lancer.bat)
- **En ligne de commande** :
  ```bash
  python run.py
  ```
  Options utiles : `--port 8080`, `--host 0.0.0.0`, `--no-browser`.

Au démarrage, la console affiche :
- l'URL locale (`http://127.0.0.1:8000`) ;
- l'**adresse Wi-Fi / LAN** (`http://192.168.x.x:8000`) à partager aux autres opérateurs pour la **saisie simultanée en temps réel** (synchronisation WebSocket + présence en direct).

---

## 4. Format des bases de données & import

> **Confidentialité** : les bases de données locales (`bdd/`, `data/`, `*.db`, `Liste_PGs_Clun_ssois.xlsx`) sont **exclues du dépôt Git** via [`.gitignore`](.gitignore). Aucune liste de noms ou de buques n'est publiée sur GitHub.

### Option A — Base par défaut au démarrage
Placez votre fichier compilé à l'emplacement :
```text
bdd/Liste_PGs_Clun_ssois.xlsx
```
C'est **ce fichier unique** qui est chargé par défaut au lancement de l'application (surchargeable via la variable d'environnement `BUQUES_BDD_FILE`).

### Option B — Import direct dans l'interface (`.xlsx` ou `.csv`)
Dans l'onglet **BDD & Paramètres**, vous pouvez importer un fichier Excel (`.xlsx`) ou CSV (`.csv`, `;`, `,` ou tabulation) à tout moment, et télécharger un fichier prêt à remplir via **Télécharger le modèle (.xlsx)**.

#### Colonnes reconnues automatiquement

| Colonne | Obligatoire ? | En-têtes reconnus (insensibles aux accents/casse) | Valeurs acceptées |
| :--- | :---: | :--- | :--- |
| **Buque** | **Oui** | `Buque`, `Buques`, `Surnom`, `Surnoms`, `Nickname` | Ex. `Pompl(Arts)`, `Rapido`, `Bas(art)` |
| **Année d'entrée / Prom'ss** | **Oui** *(pour Règle 1)* | `Prom'ss`, `Proms`, `Promo`, `Année d'entrée`, `Année`, `An'ss`, `Année d'entrée / Prom'ss` | Prom'ss (`225`, `Cl225`) **ou** année 4 chiffres (`2025`, `2025-2026` converti automatiquement en `225`) |
| **CT** | Recommandé *(défaut : `Faux`)* | `CT`, `Est CT`, `Is CT`, `Comité`, `Comité des traditions` | `Vrai` / `Faux`, `True` / `False`, `Oui` / `Non`, `1` / `0`, `X` |
| **Nom** | Non | `Nom`, `Nom de famille`, `Nom de Pek's` | Texte libre |
| **Prénom** | Non | `Prénom`, `Prenom` | Texte libre |
| **Fam's** | Non | `Fam's`, `Fams`, `Famille` | Ex. `60`, `19-115` |

#### Exemple de tableau valide

| Buque | Année d'entrée / Prom'ss | CT | Nom | Prénom | Fam's |
| :--- | :---: | :---: | :--- | :--- | :---: |
| `Pompl(Arts)` | `225` | `Faux` | `Brondin` | | `19-115` |
| `Rapido` | `2025` | `Vrai` | `Dupont` | | `60` |
| `Pastaga` | `2002` | `Vrai` | | | `96-153` |

*Remarque : une ligne marquée `CT = Vrai` avec une Prom'ss / Année connue est automatiquement vérifiée au titre de la **Règle 2 (CT)** **et** de la **Règle 1 (< 10 ans)**, sans créer de doublon.*

---

## 5. Utilisation rapide

1. **Onglet 1 — Saisie des feuilles** :
   - Renseignez votre nom d'opérateur en haut à droite.
   - Enchaînez au clavier avec **`Tab`** : `Nom de famille` → `Choix 1` → `Choix 2` → `Choix 3` → `Police 1` → `Police 2` → `Police 3` → **`Entrée`**.
   - Taper `^T` dans un choix convertit automatiquement en **`ᵀ`**.
   - Les feuilles saisies apparaissent instantanément chez tous les utilisateurs connectés.
2. **Onglet 2 — Comparaison & Export** :
   - Consultez le **tableau à 4 colonnes** (`Nom de famille`, `Choix 1`, `Choix 2`, `Choix 3`) coloré selon les 4 règles.
   - Cliquez sur n'importe quelle cellule pour ouvrir le tiroir d'inspection (détails des conflits, pourcentages orthographiques/phonétiques, marquage Règle 4 manuel ou exclusion de faux positif).
   - Exportez vers **Excel coloré (`.xlsx`)** (avec onglet `Tableau 4 colonnes` + commentaires sur les conflits + onglet `Détails & Polices`), **CSV** ou **Impression / PDF**.
3. **Onglet 3 — Testeur phonétique** :
   - Testez n'importe quelle buque isolément avant validation.

---

## 6. Utilitaire de compilation locale & Tests

- Si vous disposez de plusieurs fichiers historiques CSV dans `bdd/`, le script [`scripts/compile_bdd.py`](scripts/compile_bdd.py) permet de les fusionner et dédupliquer vers `bdd/Liste_PGs_Clun_ssois.xlsx`.
- Lancer la suite de tests automatisés :
  ```bash
  python -m unittest tests/test_app.py -v
  ```
