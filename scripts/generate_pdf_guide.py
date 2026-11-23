"""Génère le guide PDF en clun'ssois : Guide_Protocole_Buques_Clunss.pdf."""

from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile

from pypdf import PdfReader


ROOT_DIR = Path(__file__).resolve().parent.parent
CHROME_EXE = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
OUTPUT_PDF = ROOT_DIR / "Guide_Protocole_Buques_Clunss.pdf"

GUIDE_HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8" />
<title>Protocole des Buques &amp; Mode d'Emploi — Tabagn's de Clun'ss</title>
<style>
  @page {
    size: A4;
    margin: 11mm 13mm;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "Segoe UI", Roboto, Arial, sans-serif;
    color: #0f172a;
    font-size: 9.2pt;
    line-height: 1.38;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .page {
    page-break-after: always;
  }
  .page:last-child {
    page-break-after: auto;
  }
  .hero {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 65%, #312e81 100%);
    color: #ffffff;
    border-radius: 10px;
    padding: 14px 18px;
    margin-bottom: 10px;
    border-bottom: 4px solid #f59e0b;
  }
  .hero-kicker {
    font-size: 8.2pt;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #fcd34d;
    margin-bottom: 3px;
  }
  .hero h1 {
    margin: 0 0 4px;
    font-size: 17.5pt;
    line-height: 1.15;
  }
  .hero p {
    margin: 0;
    color: #e2e8f0;
    font-size: 10pt;
  }
  .section-title {
    margin: 12px 0 7px;
    font-size: 12pt;
    color: #1e3a8a;
    border-bottom: 2px solid #cbd5e1;
    padding-bottom: 3px;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .section-title span.tag {
    font-size: 8pt;
    color: #64748b;
    font-weight: 700;
    text-transform: uppercase;
  }
  .callout {
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-left: 4px solid #1d4ed8;
    border-radius: 6px;
    padding: 9px 12px;
    margin: 8px 0 11px;
  }
  .callout-gold {
    background: #fffbeb;
    border-color: #fde68a;
    border-left: 4px solid #d97706;
  }
  .rules-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 7px;
    margin-top: 6px;
  }
  .rule-card {
    border-radius: 7px;
    padding: 8px 11px;
    border: 1px solid rgba(15, 23, 42, 0.1);
    display: flex;
    gap: 10px;
    align-items: flex-start;
  }
  .rule-badge {
    min-width: 72px;
    text-align: center;
    font-weight: 800;
    font-size: 8.5pt;
    padding: 3px 6px;
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.72);
  }
  .r-violet { background: #e4c1f9; color: #4a148c; }
  .r-rouge  { background: #ffc7ce; color: #9c0006; }
  .r-orange { background: #ffd8a8; color: #9c4221; }
  .r-jaune  { background: #ffeb9c; color: #9c6500; }
  .r-vert   { background: #c6efce; color: #006100; }

  table {
    width: 100%;
    border-collapse: collapse;
    margin: 7px 0 10px;
    font-size: 9pt;
  }
  th, td {
    border: 1px solid #cbd5e1;
    padding: 5px 8px;
    text-align: left;
    vertical-align: top;
  }
  th {
    background: #0f172a;
    color: #ffffff;
    font-weight: 700;
    font-size: 8.6pt;
  }
  tr:nth-child(even) td {
    background: #f8fafc;
  }
  code, kbd {
    background: #eef2ff;
    color: #3730a3;
    padding: 1px 4px;
    border-radius: 3px;
    font-family: Consolas, monospace;
    font-size: 8.7pt;
  }
  kbd {
    background: #e2e8f0;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    font-family: inherit;
    font-weight: 700;
  }
  .two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  .box {
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    padding: 9px 11px;
    background: #ffffff;
  }
  .box h4 {
    margin: 0 0 5px;
    color: #0f172a;
    font-size: 10pt;
  }
  ul, ol {
    margin: 4px 0 6px;
    padding-left: 18px;
  }
  li {
    margin-bottom: 3px;
  }
  .footer-note {
    margin-top: 10px;
    text-align: center;
    font-size: 8.3pt;
    color: #64748b;
    border-top: 1px solid #e2e8f0;
    padding-top: 5px;
  }
</style>
</head>
<body>

<!-- ==================== PAGE 1 ==================== -->
<div class="page">
  <div class="hero">
    <div class="hero-kicker">Tabagn's de Clun'ss · Arts &amp; Métiers</div>
    <h1>Protocole des Buques &amp; Guide du Vérificateur</h1>
    <p>Traditions du bûquage des Conscrits, règles clun'ssoises et prise en main complète de l'application.</p>
  </div>

  <div class="callout callout-gold">
    <strong>Sal's les Gadz' &amp; le Comité des Traditions !</strong><br/>
    Au Tabagn's de Clun'ss, la <strong>buque</strong> accompagne un PG toute sa vie. Lors du bûquage, chaque Conscrit (1<sup>re</sup> an'ss) rend une fiche papier : au <strong>Recto</strong> figurent son nom de Pek's et ses <strong>3 propositions ordonnées</strong> ; au <strong>Verso</strong>, les <strong>3 polices d'écriture</strong> associées. Ce document fixe les usages de validation et explique comment utiliser le <em>Vérificateur de Buques</em> en équipe.
  </div>

  <div class="section-title">
    <span>1. Les 4 Usages d'Or du choix des Buques</span>
    <span class="tag">Priorité &amp; Codes Couleurs</span>
  </div>

  <p>Toute proposition est comparée à la fois sur l'<strong>écriture</strong> (orthographe normalisée) et sur la <strong>phonétique française</strong> (« ce qui sonne pareil »). Lorsqu'une buque touche plusieurs règles, l'application applique la couleur la plus critique selon l'ordre ci-dessous :</p>

  <div class="rules-grid">
    <div class="rule-card r-violet">
      <div class="rule-badge">VIOLET<br/>Règle 2</div>
      <div>
        <strong>Surnom de CT (Priorité absolue)</strong><br/>
        Il ne doit pas y avoir deux fois la même buque (ou phonétiquement identique) si elle appartient à un ancien <strong>CT</strong> (MT, RU, Veneb's, Paillasse, Major, Président aux Traditions…), quelle que soit son An'ss.
      </div>
    </div>

    <div class="rule-card r-rouge">
      <div class="rule-badge">ROUGE<br/>Règle 1</div>
      <div>
        <strong>Déjà bûquée en moins de 10 An'ss</strong><br/>
        Une buque ne doit pas revenir deux fois sur les <strong>10 dernières prom'ss</strong> (fenêtre par défaut : Cl216 à Cl225 pour la Prom'ss Cl226, réglable dans les paramètres). Les anciens PGs de plus de 10 an'ss restent affichés à titre purement informatif.
      </div>
    </div>

    <div class="rule-card r-orange">
      <div class="rule-badge">ORANGE<br/>Règle 4</div>
      <div>
        <strong>Référence problématique ou déplacée</strong><br/>
        Pas de références politiques extrêmes, propos haineux, insultes ou jeux de mots embarrassants pour la Prom'ss et la Fratern'ss. L'appli alerte via un lexique configurable et laisse le CT signaler manuellement toute buque litigieuse.
      </div>
    </div>

    <div class="rule-card r-jaune">
      <div class="rule-badge">JAUNE<br/>Règle 3</div>
      <div>
        <strong>Ressemblance dans la même Prom'ss</strong><br/>
        Deux Conscrits d'une même prom'ss ne peuvent pas recevoir des buques identiques ou trop proches à l'oreille. <em>Note : deux choix d'un même Conscrit ne se bloquent jamais entre eux.</em>
      </div>
    </div>

    <div class="rule-card r-vert">
      <div class="rule-badge">VERT<br/>Validée</div>
      <div>
        <strong>Buque utilisable !</strong><br/>
        Aucun conflit détecté sur les 4 règles. Le premier choix vert dans l'ordre (Choix 1 → Choix 2 → Choix 3) est prêt pour la validation finale et l'attribution de la police associée.
      </div>
    </div>
  </div>

  <div class="section-title">
    <span>2. Déroulement d'une séance de vérification</span>
    <span class="tag">En deux temps</span>
  </div>
  <div class="two-col">
    <div class="box">
      <h4>Étape 1 — Ramassage &amp; Saisie à plusieurs</h4>
      <p>Plusieurs Anciens / membres du CT ouvrent l'application en parallèle sur leur PC via le Wi-Fi. Chaque fiche papier est saisie en quelques secondes grâce au flux clavier <code>Tab</code> / <code>Entrée</code>. La liste se synchronise en direct.</p>
    </div>
    <div class="box">
      <h4>Étape 2 — Arbitrage &amp; Extraction</h4>
      <p>Une fois toutes les fiches rentrées, l'onglet <strong>Comparaison &amp; Export</strong> affiche le tableau à 4 colonnes colorées. Le CT inspecte les conflits, tranche les faux positifs et exporte le tableau Excel coloré final.</p>
    </div>
  </div>

  <div class="footer-note">Guide Clun'ssois du Vérificateur de Buques — Page 1 / 4</div>
</div>

<!-- ==================== PAGE 2 ==================== -->
<div class="page">
  <div class="section-title">
    <span>3. Notations Clun'ss &amp; Moteur Phonétique</span>
    <span class="tag">Comment l'appli « lit » les buques</span>
  </div>

  <p>Les buques gadz'artiques jouent avec les parenthèses, les exposants et l'alphabet grec. Une comparaison mot-à-mot classique raterait des doublons évidents : l'application développe chaque notation avant de la traduire en <strong>phonétique française</strong>.</p>

  <table>
    <thead>
      <tr>
        <th style="width: 21%;">Notation</th>
        <th style="width: 31%;">Règle de lecture clun'ssoise</th>
        <th style="width: 26%;">Exemples réels</th>
        <th style="width: 22%;">Interprétation</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>Transposée</strong><br/><code>ᵀ</code> / <code>ᵗ</code> / <code>⊤</code> / <code>^T</code></td>
        <td>Le mot entre parenthèses (ou collé avant <code>ᵀ</code>) <strong>se lit à l'envers</strong>. Taper <code>^T</code> dans l'appli le convertit automatiquement en <code>ᵀ</code>.<br/><em>Un « t » normal sans exposant n'est jamais inversé.</em></td>
        <td><code>(toto)ᵀ</code><br/><code>ᵀ(mot)</code><br/><code>Wyst(Arts)ᵀ</code><br/><code>Cl(Arts)té</code> <em>(t normal)</em></td>
        <td><code>otot</code><br/><code>tom</code><br/><code>WyststrA</code><br/><code>Clarté</code></td>
      </tr>
      <tr>
        <td><strong>Puissance zéro</strong><br/><code>^0</code> / <code>⁰</code></td>
        <td>Tout mot ou groupe élevé à la puissance 0 <strong>ne se lit pas</strong> (muet à l'oral).</td>
        <td><code>Super(test)^0</code><br/><code>(inutile)⁰Astucieux</code></td>
        <td><code>Super</code><br/><code>Astucieux</code></td>
      </tr>
      <tr>
        <td><strong>Parenthèses visuelles</strong><br/><code>(arts)</code>, <code>(...)</code></td>
        <td>Les parenthèses peuvent être purement visuelles ou signifier <em>(arts)</em>. L'appli teste les lectures orale (<em>ar</em>) et écrite (<em>art / arts</em>) et ignore les consonnes finales muettes (<code>t</code>, <code>d</code>, <code>s</code> après <code>r</code>).</td>
        <td><code>pompl(arts)</code><br/><code>Bas(art)</code><br/><code>F(arts)ina</code></td>
        <td><code>pomplar / pomplart</code><br/><code>Bazar</code> <em>(CT !)</em><br/><code>Farina / Fartsina</code></td>
      </tr>
      <tr>
        <td><strong>Carré « ² »</strong><br/><code>²</code> / <code>^2</code></td>
        <td>Double interprétation clun'ssoise testée simultanément :<br/>
          1) le mot/groupe d'avant se lit <strong>2 fois</strong> (avec règle des parenthèses) ;<br/>
          2) le <code>²</code> se lit <strong>« karse »</strong>.</td>
        <td><code>Bip²</code><br/><code>(BUG)²</code><br/><code>(J(arts))²</code><br/><code>Mou²</code> / <code>Ba²</code></td>
        <td><code>BipBip</code> &amp; <code>Bipkarse</code><br/><code>Bugbug</code> &amp; <code>Bugkarse</code><br/><code>JarJar</code> &amp; <code>Jarkarse</code><br/><code>Moukars</code> (CT) / <code>Bacars</code></td>
      </tr>
      <tr>
        <td><strong>Symboles grecs &amp; chimie</strong></td>
        <td>Les lettres grecques, maths et formules sont transcrites phonétiquement avant comparaison.</td>
        <td><code>Asph(H2O)dèle</code><br/><code>πRHANA</code> · <code>L∞πng</code><br/><code>KratΩs</code> · <code>ARTIΦS</code></td>
        <td><code>Asphodèle</code><br/><code>Piranha</code> · <code>Looping</code><br/><code>Cratos</code> · <code>Artifis</code></td>
      </tr>
    </tbody>
  </table>

  <div class="section-title">
    <span>4. Règles de phonétique française appliquées</span>
    <span class="tag">Anti-doublons à l'oreille</span>
  </div>

  <div class="two-col">
    <div class="box">
      <h4>Équivalences sonores gérées</h4>
      <ul>
        <li><code>ph</code> → <code>f</code>, <code>c/k/qu</code> → <code>k</code>, <code>c+e/i</code> → <code>s</code>, <code>ch/sh</code> → <code>ch</code></li>
        <li><code>au/eau/o</code> → <code>o</code>, <code>ou/oo</code> → <code>ou</code>, <code>ai/ei/é/è</code> → <code>é</code></li>
        <li><code>s</code> entre deux voyelles → <code>z</code> (<code>Basart</code> = <code>Bazar</code>)</li>
        <li>Nasales (<code>an/am/en/em</code>, <code>in/ain/ein</code>, <code>on/om</code>)</li>
        <li>Doubles consonnes réduites (<code>Kratoss</code> = <code>Kratos</code>)</li>
      </ul>
    </div>
    <div class="box">
      <h4>Gardes anti faux-positifs</h4>
      <ul>
        <li>Les chaînes très courtes (<strong>≤ 3 lettres</strong>, ex. <code>Bob</code> vs <code>Rob</code>) exigent une égalité exacte pour éviter de bloquer des noms courts innocents.</li>
        <li>À 4 lettres, un seuil renforcé s'applique automatiquement.</li>
        <li>Chaque conflit dans le tableau peut être inspecté et marqué <strong>« Ignorer (faux positif) »</strong> si l'homophonie est jugée acceptable par le CT.</li>
      </ul>
    </div>
  </div>

  <div class="footer-note">Guide Clun'ssois du Vérificateur de Buques — Page 2 / 4</div>
</div>

<!-- ==================== PAGE 3 ==================== -->
<div class="page">
  <div class="section-title">
    <span>5. Utilisation de l'application — Pas à pas</span>
    <span class="tag">Saisie &amp; Comparaison</span>
  </div>

  <div class="callout">
    <strong>Lancement express :</strong><br/>
    1. Lancez <code>lancer.bat</code> (Windows) ou <code>python run.py</code> dans le dossier du projet.<br/>
    2. Le navigateur s'ouvre sur <code>http://127.0.0.1:8000</code>. Pour travailler à plusieurs, cliquez sur <strong>« Wi-Fi : http://192.168.x.x:8000 »</strong> dans la barre du haut et partagez ce lien aux autres opérateurs sur le même réseau.
  </div>

  <div class="two-col">
    <div class="box">
      <h4>Onglet 1 — Saisie ultra-rapide (Étape 1)</h4>
      <ol>
        <li>Indiquez votre prénom d'opérateur en haut à droite (ex. <em>Rapido</em>).</li>
        <li>Saisissez les fiches au clavier avec la seule touche <kbd>Tab</kbd> :<br/>
          <code>Nom</code> → <kbd>Tab</kbd> → <code>Choix 1</code> → <kbd>Tab</kbd> → <code>Choix 2</code> → <kbd>Tab</kbd> → <code>Choix 3</code> → <kbd>Tab</kbd> → <code>Police 1</code> → <kbd>Tab</kbd> → <code>Police 2</code> → <kbd>Tab</kbd> → <code>Police 3</code> → <kbd>Entrée</kbd>.</li>
        <li>Le champ <em>Prénom</em> et les boutons de symboles sont ignorés par <kbd>Tab</kbd> pour garder un rythme maximal (cliquables à la souris au besoin).</li>
        <li>Taper <code>^T</code> insère directement <code>ᵀ</code> ; la barre de raccourcis insère <code>(arts)</code>, <code>ᵀ</code>, <code>^0</code>, <code>²</code>, <code>π</code>, <code>φ</code>, <code>Ω</code>, <code>(H2O)</code> sans perdre le focus.</li>
        <li>Une alerte s'affiche si le même <strong>Nom de famille</strong> est déjà saisi par un collègue.</li>
      </ol>
    </div>

    <div class="box">
      <h4>Onglet 2 — Comparaison &amp; Export (Étape 2)</h4>
      <ol>
        <li>Cliquez sur <strong>« Passer à la comparaison → »</strong>.</li>
        <li>Consultez les compteurs en haut (<em>Vert</em>, <em>Rouge</em>, <em>Violet</em>, <em>Jaune</em>, <em>Orange</em>, et surtout <strong>« Sans aucun choix vert »</strong> pour repérer les Conscrits à revoir en priorité).</li>
        <li>Le tableau affiche les <strong>4 colonnes demandées</strong> : <code>Nom de famille</code>, <code>Choix 1</code>, <code>Choix 2</code>, <code>Choix 3</code>.</li>
        <li><strong>Cliquez sur n'importe quelle cellule</strong> pour ouvrir le tiroir d'inspection :
          <ul>
            <li>Lectures phonétiques détaillées et scores (%).</li>
            <li>Liste exacte des PGs / CTs / Conscrits en conflit.</li>
            <li>Boutons <em>Signaler problématique (R4)</em> ou <em>Ignorer ce faux positif</em> (synchronisé pour tous).</li>
          </ul>
        </li>
        <li>Cliquez sur <strong>« Exporter Excel coloré (.xlsx) »</strong> pour générer le tableau final avec couleurs et commentaires.</li>
      </ol>
    </div>
  </div>

  <div class="section-title">
    <span>6. Testeur phonétique &amp; Sensibilité</span>
    <span class="tag">Outils du CT</span>
  </div>
  <div class="box">
    <p style="margin:0;">
      • <strong>Testeur phonétique (Onglet 3)</strong> : tapez une proposition isolée pendant le bûquage pour vérifier en direct comment elle est lue (<code>ᵀ</code>, <code>^0</code>, <code>²</code>, <code>(arts)</code>) et quels anciens PGs ou CTs elle accroche.<br/>
      • <strong>Réglage des seuils (bouton « Sensibilité ▾ »)</strong> : permet d'ajuster temporairement ou définitivement les seuils de similarité (défaut : <strong>85%</strong> pour PGs/CTs, <strong>75%</strong> au sein de la Prom'ss) et de choisir si la Règle 3 compare les 3 choix entre eux ou uniquement au Choix 1 des autres.
    </p>
  </div>

  <div class="footer-note">Guide Clun'ssois du Vérificateur de Buques — Page 3 / 4</div>
</div>

<!-- ==================== PAGE 4 ==================== -->
<div class="page">
  <div class="section-title">
    <span>7. Préparer &amp; Importer la Base de Données</span>
    <span class="tag">Format Excel (.xlsx) &amp; CSV</span>
  </div>

  <p>Pour préserver l'anonymat des Anciens sur GitHub, aucune base de données n'est stockée dans le dépôt public. Au démarrage, l'application lit automatiquement le fichier unique :</p>
  <div class="callout">
    <code>bdd/Liste_PGs_Clun_ssois.xlsx</code> &nbsp; <em>(modifiable depuis l'onglet <strong>BDD &amp; Paramètres</strong> via import <code>.xlsx</code> ou <code>.csv</code>)</em>
  </div>

  <p>L'importateur reconnaît automatiquement les colonnes suivantes (un modèle vierge est téléchargeable dans l'onglet 4) :</p>

  <table>
    <thead>
      <tr>
        <th>Colonne</th>
        <th>Statut</th>
        <th>Noms d'en-têtes reconnus</th>
        <th>Format attendu &amp; astuces</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><strong>Buque</strong></td>
        <td><strong>Obligatoire</strong></td>
        <td><code>Buque</code>, <code>Surnom</code>, <code>Nickname</code></td>
        <td>Surnom tel qu'écrit avec ses notations (<code>Pompl(Arts)</code>, <code>KratΩs</code>…).</td>
      </tr>
      <tr>
        <td><strong>Année d'entrée / Prom'ss</strong></td>
        <td><strong>Obligatoire</strong> (PG)</td>
        <td><code>Prom'ss</code>, <code>Proms</code>, <code>Promo</code>, <code>Année d'entrée</code>, <code>Année</code>, <code>An'ss</code></td>
        <td>Numéro de Prom'ss (<code>225</code>, <code>Cl225</code>) <strong>ou</strong> année d'entrée à 4 chiffres (<code>2025</code>, <code>2025-2026</code> → converti en <code>225</code>).</td>
      </tr>
      <tr>
        <td><strong>CT</strong></td>
        <td>Recommandé</td>
        <td><code>CT</code>, <code>Est CT</code>, <code>Comité</code></td>
        <td><code>Vrai</code> / <code>Faux</code> (ou <code>Oui</code>/<code>Non</code>, <code>1</code>/<code>0</code>, <code>X</code>). Défaut : <code>Faux</code>. Une ligne <code>CT = Vrai</code> vérifie Règle 2 <strong>et</strong> Règle 1 (si Prom'ss connue).</td>
      </tr>
      <tr>
        <td><strong>Nom / Prénom / Fam's</strong></td>
        <td>Optionnel</td>
        <td><code>Nom</code>, <code>Prénom</code>, <code>Fam's</code></td>
        <td>Affiché dans le tiroir d'inspection et la recherche BDD pour identifier les Anciens.</td>
      </tr>
    </tbody>
  </table>

  <div class="section-title">
    <span>8. Checklist du CT avant de bûquer la Prom'ss</span>
    <span class="tag">Bonnes pratiques</span>
  </div>
  <div class="box">
    <ul>
      <li><strong>Vérifier la couverture des 10 dernières Prom'ss</strong> dans l'onglet <em>BDD &amp; Paramètres</em> : toute prom'ss affichée en rouge (<code>0</code> ligne) doit être complétée par import Excel/CSV avant la séance (ex. prom'ss sorties récemment).</li>
      <li><strong>Relire le lexique Règle 4</strong> pour ajouter d'éventuelles références d'actualité ou blagues internes sensibles de l'année.</li>
      <li><strong>Exporter le fichier Excel coloré</strong> à l'issue de la séance : il conserve la mise en couleur des 4 règles, les commentaires de conflits sur chaque case et un second onglet complet avec les polices d'écriture.</li>
    </ul>
  </div>

  <div class="footer-note">Fratern'ss &amp; Traditions — Tabagn's de Clun'ss · Page 4 / 4</div>
</div>

</body>
</html>
"""


def generate_pdf() -> Path:
    if not CHROME_EXE.exists():
        raise FileNotFoundError(f"Chrome introuvable : {CHROME_EXE}")

    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "guide.html"
        html_path.write_text(GUIDE_HTML, encoding="utf-8")

        cmd = [
            str(CHROME_EXE),
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={OUTPUT_PDF}",
            html_path.as_uri(),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if not OUTPUT_PDF.exists() or OUTPUT_PDF.stat().st_size == 0:
            raise RuntimeError(f"Échec de génération PDF : {proc.stderr}")

    reader = PdfReader(str(OUTPUT_PDF))
    num_pages = len(reader.pages)
    if num_pages != 4:
        raise RuntimeError(f"Nombre de pages inattendu : {num_pages} (attendu : 4)")
    for i, page in enumerate(reader.pages, start=1):
        txt = (page.extract_text() or "").strip()
        if len(txt) < 100:
            raise RuntimeError(f"Page {i} quasi vide ({len(txt)} caractères)")

    print(f"PDF généré avec succès : {OUTPUT_PDF.name} ({num_pages} pages, {OUTPUT_PDF.stat().st_size} octets)")
    return OUTPUT_PDF


if __name__ == "__main__":
    generate_pdf()
