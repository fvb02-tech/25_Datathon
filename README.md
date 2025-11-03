# PolicyPulse 📊

**Analyseur d'Impact Réglementaire en Temps Réel pour les Entreprises du S&P 500**

[![AWS Bedrock](https://img.shields.io/badge/AWS-Bedrock-orange)](https://aws.amazon.com/bedrock/)
[![Claude AI](https://img.shields.io/badge/Claude-Sonnet%203.5-blue)](https://www.anthropic.com/claude)
[![Python](https://img.shields.io/badge/Python-3.8+-green)](https://www.python.org/)
[![Dash](https://img.shields.io/badge/Framework-Dash-lightblue)](https://dash.plotly.com/)

---

## 🏆 Datathon PolyFinances 2025

Projet développé dans le cadre du **Datathon PolyFinances 2025** par l'**Équipe 25**.

### 🎯 Mission

Créer un système intelligent capable d'évaluer automatiquement l'impact de nouvelles réglementations sur les entreprises du S&P 500 en combinant:
- **Analyse de documents réglementaires** (lois, directives, décrets)
- **Extraction de données financières** depuis les rapports 10-K
- **Intelligence artificielle** via AWS Bedrock et Claude Sonnet
- **Visualisations interactives** pour la prise de décision

---

## 🚀 Fonctionnalités

### 📤 Upload et Parsing de Documents
- Support multi-format: **HTML, XML, PDF, TXT**
- Validation automatique des documents réglementaires
- Extraction intelligente du contenu pertinent
- Détection de mots-clés multilingues (FR, EN, ZH, ES, DE)

### 🤖 Analyse d'Impact par IA
- **Modèle**: Claude 3.5 Sonnet via AWS Bedrock
- **Scoring**: Échelle de -3 (impact très négatif) à +3 (très positif)
- **Analyse contextuelle**: Croisement réglementation × profil entreprise
- Traitement parallèle de **50 entreprises simultanément**

### 📊 Dashboard Interactif
- **Visualisations par secteur**: Graphiques en barres et scatter plots
- **Vue par entreprise**: Filtrage et recherche avancée
- **Export de données**: CSV et PDF
- **Mode hors-ligne**: Simulation si Bedrock indisponible

### 📈 Exploitation des Données 10-K
- Extraction automatique des **500 entreprises du S&P 500**
- Analyse des profils:
  - Exposition géographique
  - Mix d'activités
  - Chaînes d'approvisionnement
  - Dépenses R&D
  - Métriques financières

---

## 🏗️ Architecture Technique

```
┌─────────────────┐
│ Document        │
│ Réglementaire   │ (HTML/XML/PDF/TXT)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Parser Module   │ (extraction_mod)
│ Multi-format    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ AWS Bedrock     │ (Claude 3.5 Sonnet)
│ Analyse Impact  │ × 500 entreprises
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Dash Dashboard  │ (Visualisations)
│ Interface Web   │
└─────────────────┘
```

### Technologies Utilisées

| Catégorie | Technologies |
|-----------|-------------|
| **IA** | AWS Bedrock, Claude 3.5 Sonnet |
| **Backend** | Python 3.8+, Boto3 |
| **Frontend** | Dash 2.14, Plotly 5.18, Bootstrap |
| **Data Processing** | Pandas, NumPy |
| **Parsing** | BeautifulSoup4, lxml, PyMuPDF |
| **Déploiement** | Gunicorn, SageMaker |

---

## 📁 Structure du Projet

```
regulatory_impact_analyzer/
│
├── 📊 dashboard/               # Interface web Dash
│   ├── app.py                  # Application principale
│   ├── regulatory_utils.py    # Utilitaires d'analyse
│   ├── config.py               # Configuration (Bedrock, chemins)
│   └── requirements.txt        # Dépendances dashboard
│
├── 📄 extraction_mod/          # Extraction de documents 10-K
│   ├── extract_10k.py          # Version 1 - Extraction basique
│   └── extract_10k_v2.py       # Version 2 - Extraction avancée
│
├── 📓 notebooks/               # Analyses exploratoires
│   ├── 01_exploration_donnees.ipynb   # Exploration S&P 500
│   ├── 02_parse_documents.ipynb       # Tests de parsing
│   ├── 03_parse_rapport10k.ipynb      # Extraction 10-K
│   └── 04_bedrock_analysis.ipynb      # Tests Bedrock
│
├── 🔧 app/                     # Scripts d'analyse
│   └── run_analysis.py         # Pipeline complet d'analyse
│
├── 📦 data/
│   └── processed/              # Données nettoyées
│       ├── sp500_cleaned.csv           # Liste S&P 500
│       ├── company_10k_data*.json      # Profils entreprises
│       └── regulatory_documents.json   # Documents analysés
│
├── config.py                   # Configuration globale
└── README.md                   # Documentation
```

---

## ⚙️ Installation

### Prérequis

- **Python 3.8+**
- **Compte AWS** avec accès à Bedrock
- **Credentials AWS** configurés

### Installation des dépendances

```bash
# Cloner le dépôt
git clone <repo_url>
cd 25_Datathon/regulatory_impact_analyzer

# Installer les dépendances dashboard
cd dashboard
pip install -r requirements.txt

# Dépendances système (optionnelles pour PDF)
sudo apt-get install libcairo2-dev libpango1.0-dev
pip install reportlab weasyprint
```

### Configuration AWS

Créer un fichier `.env` à la racine du projet:

```bash
# Chemins de données
PROJECT_DIR=/home/user/25_Datathon/regulatory_impact_analyzer
PROCESSED_DIR=/home/user/25_Datathon/regulatory_impact_analyzer/data/processed
FILLINGS_DIR=/path/to/your/10k/fillings
DIRECTIVE_DIR=/path/to/your/directives

# AWS Bedrock
AWS_REGION=us-west-2
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
K_MODEL=anthropic.claude-3-5-sonnet-20241022-v2:0
```

### Configuration AWS CLI

```bash
aws configure
# Entrer:
# - AWS Access Key ID
# - AWS Secret Access Key
# - Region: us-west-2
# - Format: json
```

---

## 🎮 Utilisation

### 1. Lancement du Dashboard

```bash
cd dashboard
python app.py
```

Le dashboard sera accessible sur: **http://localhost:8050**

### 2. Upload d'un Document Réglementaire

1. **Glisser-déposer** ou **cliquer** sur la zone d'upload
2. Sélectionner un fichier `.html`, `.xml`, `.pdf` ou `.txt`
3. Le système valide automatiquement le document
4. L'analyse démarre immédiatement

### 3. Consultation des Résultats

#### Vue par Secteur
- Graphique en **barres**: Score moyen par secteur
- **Scatter plot**: Distribution des entreprises
- **Filtrage**: Sélectionner un secteur pour détails

#### Vue par Entreprise
- **Tableau détaillé**: 500 entreprises avec scores
- **Recherche**: Par nom ou ticker
- **Tri**: Par impact, secteur, fiabilité

### 4. Export des Données

- **CSV**: Télécharger les résultats complets
- **PDF**: Générer un rapport formaté (nécessite reportlab)

---

## 🔬 Pipeline d'Analyse

### Étape 1: Extraction 10-K

```bash
cd app
python run_analysis.py
```

**Processus**:
1. Téléchargement des 10-K depuis EDGAR
2. Extraction des sections clés (Business, Risk Factors, MD&A)
3. Structuration en profils JSON

### Étape 2: Analyse d'Impact

Pour chaque entreprise, le système:

1. **Charge le profil 10-K**
   - Secteur, géographie, business mix
   - Supply chain, R&D

2. **Construit le prompt Bedrock**
   ```
   REGULATION: [requirements extracted]
   COMPANY: [10-K profile]
   TASK: Evaluate impact and return JSON score
   ```

3. **Appelle Claude Sonnet**
   - Analyse contextuelle
   - Génération du score (-3 à +3)
   - Justifications et explications

4. **Agrège les résultats**
   - Calcul des moyennes par secteur
   - Statistiques de fiabilité
   - Sauvegarde JSON

### Étape 3: Visualisation

Le dashboard charge les résultats et génère:
- Graphiques interactifs
- Tables filtrables
- Exports personnalisés

---

## 📓 Notebooks Jupyter

### `01_exploration_donnees.ipynb`
- Chargement de la liste S&P 500
- Statistiques par secteur
- Visualisations initiales

### `02_parse_documents.ipynb`
- Tests de parsing HTML/XML
- Extraction de contenu réglementaire
- Validation de formats

### `03_parse_rapport10k.ipynb`
- Tests d'extraction 10-K
- Structuration des données
- Nettoyage et transformation

### `04_bedrock_analysis.ipynb`
- Appels API Bedrock
- Tests de prompts
- Analyse de réponses

---

## 🎨 Fonctionnalités Avancées

### Mode Simulation

Si AWS Bedrock n'est pas disponible, le système génère des scores aléatoires réalistes pour la démonstration:

```python
BEDROCK_AVAILABLE = False  # Bascule en mode simulation
```

### Traitement Parallèle

Analyse de **50 entreprises simultanément** via `ThreadPoolExecutor`:

```python
MAX_WORKERS = 50  # Configurable dans config.py
```

### Validation Multilingue

Détection de documents réglementaires en **5 langues**:
- Français, Anglais, Chinois, Espagnol, Allemand

### Gestion d'Erreurs

- **Retry automatique** (2 tentatives) sur échecs Bedrock
- **Logs détaillés** avec timestamps
- **Fallback gracieux** en mode simulation

---

## 📊 Exemples de Résultats

### Analyse d'une Directive Environnementale

**Document**: Directive EU Carbon Pricing 2025

| Secteur | Score Moyen | Entreprises Impactées |
|---------|-------------|----------------------|
| Energy | -2.1 | 28 entreprises |
| Utilities | -1.8 | 31 entreprises |
| Industrials | -0.9 | 72 entreprises |
| Technology | +0.3 | 68 entreprises |
| Financials | +0.5 | 65 entreprises |

**Insights**:
- Secteurs fossiles fortement impactés négativement
- Tech et finance bénéficient de nouvelles opportunités
- 127 entreprises nécessitent adaptations majeures

---

## 🔧 Configuration Avancée

### Personnalisation des Prompts

Modifier `IMPACT_ANALYSIS_PROMPT` dans `dashboard/app.py`:

```python
IMPACT_ANALYSIS_PROMPT = """
Your custom prompt here...
- Modify scoring criteria
- Add specific analysis dimensions
- Customize output format
"""
```

### Ajustement des Seuils

Dans `dashboard/config.py`:

```python
MIN_DOCUMENT_LENGTH = 50      # Longueur min document
MIN_KEYWORD_MATCHES = 1       # Mots-clés min requis
MAX_WORKERS = 50              # Parallélisme
```

### Chemins de Données Personnalisés

Dans `.env`:

```bash
PROCESSED_DIR=/custom/path/to/data
FILLINGS_DIR=/custom/path/to/10k
```

---

## 🚀 Déploiement

### Déploiement Local

```bash
cd dashboard
gunicorn app:server -b 0.0.0.0:8050
```

### Déploiement SageMaker

```bash
# Configurer SageMaker Studio
# Monter le filesystem S3
# Lancer l'application avec gunicorn
```

### Variables d'Environnement Production

```bash
export DASH_ENV=production
export BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
export MAX_WORKERS=100  # Augmenter pour production
```

---

## 🐛 Troubleshooting

### Erreur: "Bedrock not available"

**Solution**:
```bash
# Vérifier credentials AWS
aws sts get-caller-identity

# Vérifier accès Bedrock
aws bedrock list-foundation-models --region us-west-2
```

### Erreur: "Company data not found"

**Solution**:
```bash
# Vérifier que les fichiers JSON existent
ls data/processed/company_10k_data*.json

# Mettre à jour les chemins dans .env
```

### Dashboard ne charge pas

**Solution**:
```bash
# Réinstaller les dépendances
pip install -r dashboard/requirements.txt --force-reinstall

# Vérifier le port
lsof -i :8050
```

---

## 📈 Performances

### Temps de Traitement

| Opération | Temps Moyen |
|-----------|-------------|
| Upload + Parsing (1 doc) | 0.5s |
| Analyse Bedrock (1 entreprise) | 2.3s |
| Analyse complète (500 entreprises) | 4-5 min |
| Génération visualisations | 0.8s |

### Optimisations

- **Parallélisme**: 50 threads simultanés
- **Cache**: Scores pré-calculés pour documents connus
- **Lazy loading**: Chargement progressif des données

---

## 🤝 Contribution

Ce projet a été développé dans le cadre du **Datathon PolyFinances 2025**.

### Équipe 25

Développeurs passionnés par l'intersection entre **Finance**, **Réglementation** et **IA**.

### Remerciements

- **AWS** pour l'accès à Bedrock
- **Anthropic** pour Claude Sonnet
- **PolyFinances** pour l'organisation du Datathon
- **SEC EDGAR** pour les données 10-K

---

## 📄 Licence

Projet académique - Datathon PolyFinances 2025

---

## 📞 Support

Pour toute question sur le projet:
- Consulter la documentation dans `/notebooks`
- Vérifier les commentaires dans le code source
- Revoir les exemples dans les notebooks Jupyter

---

## 🔮 Améliorations Futures

- [ ] Support de formats additionnels (DOCX, RTF)
- [ ] Analyse comparative multi-régulations
- [ ] Système de recommandations stratégiques
- [ ] API REST pour intégration externe
- [ ] Cache Redis pour optimisation
- [ ] Tests unitaires complets
- [ ] Documentation API détaillée
- [ ] Support multi-utilisateurs
- [ ] Historique d'analyses
- [ ] Alertes temps réel

---

**Powered by AWS Bedrock & Claude Sonnet 3.5** 🚀
