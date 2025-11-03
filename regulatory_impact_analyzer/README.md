# PolicyPulse - Regulatory Impact Analyzer

Analyse d'impact réglementaire en temps réel pour les entreprises du S&P 500.

## Démarrage rapide

```bash
# Installation des dépendances
cd dashboard
pip install -r requirements.txt

# Lancement du dashboard
python app.py
```

Accès: http://localhost:8050

## 📁 Structure

```
regulatory_impact_analyzer/
├── dashboard/          # Interface web Dash
│   ├── app.py         # Application principale
│   ├── regulatory_utils.py  # Utilitaires d'analyse
│   └── config.py      # Configuration
├── data/
│   └── processed/     # Données des entreprises S&P 500
├── extraction_mod/    # Extraction de documents 10-K
├── notebooks/         # Analyses Jupyter
└── app/              # Scripts d'analyse
```

## 🔧 Fonctionnalités

- **Upload de documents** réglementaires (HTML, XML)
- **Analyse d'impact** via AWS Bedrock (Claude Sonnet)
- **Visualisations** par secteur et entreprise
- **Export** CSV/PDF des résultats
- **Mode simulation** si Bedrock indisponible

## ⚙️ Configuration

Créer un fichier `.env`:
```
AWS_REGION=us-west-2
BEDROCK_MODEL_ID=anthropic.claude-3-sonnet-20240229-v1:0
```

## 📊 Utilisation

1. Uploader un document réglementaire
2. L'analyse s'exécute automatiquement
3. Consulter les résultats par secteur/entreprise
4. Exporter les données

## 🏆 Datathon PolyFinances 2025

Équipe 25 - Powered by AWS Bedrock & Claude Sonnet