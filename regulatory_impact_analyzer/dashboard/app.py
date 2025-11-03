#!/usr/bin/env python3
"""
PolicyPulse - Analyse d'impact réglementaire en temps réel
Dashboard avec upload de documents et analyse sentimentale
Datathon PolyFinances 2025
"""

import dash
from dash import dcc, html, Input, Output, State, callback_context, no_update
import dash_bootstrap_components as dbc
from dash.exceptions import PreventUpdate
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import json
from pathlib import Path
import base64
import io
from datetime import datetime
import warnings
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
warnings.filterwarnings('ignore')

from regulatory_utils import (
    parse_any_format,
    validate_regulatory_document as validate_document_internal,
    load_company_data,
    format_company_profile,
    load_precalculated_scores
)
from config import BEDROCK_CONFIG, MAX_WORKERS

# ============================================================================
# IMPORTS BEDROCK POUR ANALYSE TEMPS RÉEL
# ============================================================================

try:
    import boto3
    BEDROCK_CLIENT = boto3.client('bedrock-runtime', region_name=BEDROCK_CONFIG['region'])
    MODEL_ID = BEDROCK_CONFIG['model_id']
    BEDROCK_AVAILABLE = True
except Exception:
    BEDROCK_CLIENT = None
    MODEL_ID = None
    BEDROCK_AVAILABLE = False

# ============================================================================
# FONCTIONS D'ANALYSE TEMPS RÉEL BEDROCK
# ============================================================================

IMPACT_ANALYSIS_PROMPT = """You are a financial analyst evaluating regulatory impact on companies.

**REGULATION:**
Name: {regulation_name}
Key Requirements: {requirements}

**COMPANY PROFILE:**
Name: {company_name} ({ticker})
Sector: {sector}
Geographic Exposure: {geography}
Business Mix: {business_mix}
Supply Chain: {supply_chain}
R&D Spending: {r_and_d}

**TASK:**
Evaluate the regulatory impact on this company. Return ONLY a valid JSON object:

{{
  "impact_score": <number from -3 to +3>,
  "sentiment": "<one of: VERY_NEGATIVE, NEGATIVE, NEUTRAL, POSITIVE, VERY_POSITIVE>",
  "reliability": <number from 0 to 1>,
  "reasons": ["reason 1", "reason 2"],
  "explanation": "<2-3 sentences explaining the score>"
}}

**SCORING GUIDE:**
- **-3 to -1.5 (VERY_NEGATIVE)**: Severe negative impact, fundamental business model threat
- **-1.5 to -0.5 (NEGATIVE)**: Notable negative impact, adaptation required
- **-0.5 to 0.5 (NEUTRAL)**: Minimal or balanced impact
- **+0.5 to +1.5 (POSITIVE)**: Notable competitive advantage or new opportunities
- **+1.5 to +3 (VERY_POSITIVE)**: Major competitive advantage, strong growth catalyst

**CRITICAL:** Return ONLY the JSON object, no other text."""

def load_company_data_from_json():
    """Charge les données des 500 entreprises depuis company_10k_data*.json"""
    return load_company_data()

def format_company_info(company_data: Dict) -> Dict[str, str]:
    """Formate les informations de l'entreprise pour le prompt"""
    return format_company_profile(company_data)

def call_bedrock(prompt: str) -> Optional[Dict]:
    """Appelle Bedrock pour l'analyse d'impact"""
    if not BEDROCK_AVAILABLE:
        
        return None
    
    for attempt in range(2):
        try:
            response = BEDROCK_CLIENT.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2000,
                    "temperature": 0.1,
                    "messages": [{
                        "role": "user",
                        "content": [{"type": "text", "text": prompt}]
                    }]
                })
            )
            
            response_body = json.loads(response['body'].read())
            response_text = response_body['content'][0]['text']
            
            # Debug: afficher la réponse brute
            # 
            
            # Nettoyer markdown
            response_text = response_text.strip()
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            if response_text.startswith('```'):
                response_text = response_text[3:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            
            result = json.loads(response_text.strip())
            return result
        
        except json.JSONDecodeError as e:
            
            print(f"   Réponse: {response_text[:300]}")
            if attempt < 1:
                time.sleep(1)
                continue
            return None
        except Exception as e:
            
            if attempt < 1:
                time.sleep(1)
                continue
            return None
    
    return None

def analyze_company_regulation_pair(company_data: Dict, regulation: Dict) -> Optional[Dict]:
    """Analyse l'impact d'une régulation sur une entreprise via Bedrock"""
    company_info = format_company_info(company_data)
    ticker = company_data.get('ticker', 'UNK')
    
    prompt = IMPACT_ANALYSIS_PROMPT.format(
        regulation_name=regulation.get('title', 'Unknown'),
        requirements=regulation.get('requirements', 'Not specified'),
        **company_info
    )
    
    analysis = call_bedrock(prompt)
    
    if analysis:
        return {
            'ticker': ticker,
            'company_name': company_info['company_name'],
            'sector': company_info['sector'],
            'impact_score': round(analysis.get('impact_score', 0), 2),
            'sentiment': analysis.get('sentiment', 'NEUTRAL'),
            'reliability': round(analysis.get('reliability', 0.5), 2),
            'reasons': analysis.get('reasons', [])[:2],
            'date_analyzed': datetime.now().strftime('%Y-%m-%d %H:%M')
        }
    
    return None

def parse_uploaded_document(contents, filename):
    """Parse le document uploadé (PDF ou TXT)"""
    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        
        if filename.endswith('.txt'):
            text = decoded.decode('utf-8')
        elif filename.endswith('.pdf'):
            try:
                import pdfplumber
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                    tmp.write(decoded)
                    tmp_path = tmp.name
                with pdfplumber.open(tmp_path) as pdf:
                    text = "\n".join([page.extract_text() or "" for page in pdf.pages])
                Path(tmp_path).unlink()
                return text
            except:
                text = decoded.decode('utf-8', errors='ignore')
        else:
            text = decoded.decode('utf-8', errors='ignore')
        
        return text
    except Exception as e:
        
        return ""

def validate_regulatory_document(text: str) -> bool:
    """Valide que le document est bien réglementaire"""
    is_valid, _ = validate_document_internal(text)
    return is_valid

def analyze_regulation_with_bedrock(text: str, filename: str, progress_callback=None) -> List[Dict]:
    """Analyse complète d'une régulation via Bedrock sur toutes les entreprises avec callback de progression"""
    
    companies = load_company_data_from_json()
    
    if not companies:
        return []
    
    total = len(companies)
    
    regulation = {
        'title': filename.replace('.pdf', '').replace('.txt', '').replace('.xml', '').replace('.html', ''),
        'requirements': text[:500] + "..." if len(text) > 500 else text
    }
    
    results = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(analyze_company_regulation_pair, company, regulation): i
            for i, company in enumerate(companies)
        }
        
        completed = 0
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
            
            completed += 1
            
            if progress_callback:
                progress_callback(completed, total)
            
            time.sleep(0.01)
    
    return results

# ============================================================================
# CONFIGURATION & INITIALISATION
# ============================================================================

app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css",
        "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap"
    ],
    suppress_callback_exceptions=True,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"}
    ]
)

server = app.server
app.title = "PolicyPulse | Analyse d'Impact Réglementaire"

# Palette de couleurs ultra-moderne avec excellent contraste
COLORS = {
    'primary': '#6366f1',        # Indigo vif
    'primary_dark': '#4f46e5',   # Indigo foncé
    'secondary': '#8b5cf6',      # Violet
    'success': '#10b981',        # Emerald
    'warning': '#f59e0b',        # Amber
    'danger': '#ef4444',         # Red
    'info': '#3b82f6',           # Blue
    'background': '#f8fafc',     # Slate 50
    'surface': '#ffffff',        # Blanc pur
    'surface_dark': '#f1f5f9',   # Slate 100
    'text_primary': '#0f172a',   # Slate 900
    'text_secondary': '#475569', # Slate 600
    'border': '#e2e8f0',         # Slate 200
    'shadow': 'rgba(15, 23, 42, 0.08)',
}

# Dégradés modernes
GRADIENTS = {
    'primary': 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
    'success': 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
    'danger': 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)',
    'warning': 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
    'info': 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
}

# Mapping des sentiments (remplace les recommandations)
SENTIMENT_CONFIG = {
    'VERY_NEGATIVE': {
        'label': 'Très Négatif',
        'color': '#dc2626',
        'icon': 'fas fa-arrow-down',
        'range': (-3, -1.5),
        'emoji': 'fas fa-arrow-down'
    },
    'NEGATIVE': {
        'label': 'Négatif',
        'color': '#f59e0b',
        'icon': 'fas fa-arrow-trend-down',
        'range': (-1.5, -0.5),
        'emoji': 'fas fa-arrow-trend-down'
    },
    'NEUTRAL': {
        'label': 'Neutre',
        'color': '#6b7280',
        'icon': 'fas fa-minus',
        'range': (-0.5, 0.5),
        'emoji': 'fas fa-minus'
    },
    'POSITIVE': {
        'label': 'Positif',
        'color': '#10b981',
        'icon': 'fas fa-arrow-trend-up',
        'range': (0.5, 1.5),
        'emoji': 'fas fa-arrow-trend-up'
    },
    'VERY_POSITIVE': {
        'label': 'Très Positif',
        'color': '#059669',
        'icon': 'fas fa-arrow-up',
        'range': (1.5, 3),
        'emoji': 'fas fa-arrow-up'
    }
}

def get_sentiment_from_score(score):
    """Détermine le sentiment basé sur le score"""
    for sentiment, config in SENTIMENT_CONFIG.items():
        if config['range'][0] <= score < config['range'][1]:
            return sentiment
    if score >= 1.5:
        return 'VERY_POSITIVE'
    return 'VERY_NEGATIVE'

# CSS Personnalisé ultra-moderne
CUSTOM_CSS = """
/* Variables et animations */
@keyframes fadeInUp {
    from {
        opacity: 0;
        transform: translateY(30px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

@keyframes shimmer {
    0% { background-position: -1000px 0; }
    100% { background-position: 1000px 0; }
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.8; }
}

/* Style global */
body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: #f8fafc;
    color: #0f172a;
}

/* Upload zone moderne */
.upload-zone {
    border: 3px dashed #cbd5e1;
    border-radius: 20px;
    background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
    padding: 60px 40px;
    text-align: center;
    transition: all 0.3s ease;
    cursor: pointer;
    position: relative;
    overflow: hidden;
}

.upload-zone::before {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 100%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(99, 102, 241, 0.1), transparent);
    transition: left 0.5s;
}

.upload-zone:hover {
    border-color: #6366f1;
    background: linear-gradient(135deg, #ffffff 0%, #f0f4ff 100%);
    transform: translateY(-5px);
    box-shadow: 0 20px 40px rgba(99, 102, 241, 0.15);
}

.upload-zone:hover::before {
    left: 100%;
}

/* Cartes modernes avec ombre douce */
.modern-card {
    background: white;
    border-radius: 24px;
    border: 1px solid #e2e8f0;
    padding: 32px;
    transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
    box-shadow: 0 4px 6px rgba(15, 23, 42, 0.04);
    animation: fadeInUp 0.6s ease-out;
}

.modern-card:hover {
    transform: translateY(-8px);
    box-shadow: 0 20px 40px rgba(15, 23, 42, 0.12);
    border-color: #cbd5e1;
}

/* Cartes secteur large */
.sector-card {
    background: white;
    border-radius: 20px;
    border: 1px solid #e2e8f0;
    padding: 24px;
    margin-bottom: 16px;
    transition: all 0.3s ease;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
}

.sector-card:hover {
    transform: translateX(8px);
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.1);
    border-color: #6366f1;
}

/* Cartes entreprise */
.company-card-new {
    background: white;
    border-radius: 20px;
    border: 1px solid #e2e8f0;
    padding: 28px;
    transition: all 0.3s ease;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
    height: 100%;
}

.company-card-new:hover {
    transform: translateY(-8px);
    box-shadow: 0 16px 32px rgba(15, 23, 42, 0.12);
    border-color: #6366f1;
}

/* Badge sentiment */
.sentiment-badge {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 20px;
    border-radius: 50px;
    font-weight: 600;
    font-size: 0.9rem;
    letter-spacing: 0.3px;
    transition: all 0.3s ease;
}

.sentiment-badge:hover {
    transform: scale(1.05);
    box-shadow: 0 4px 12px currentColor;
}

/* Score display moderne */
.score-display {
    background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
    border: 2px solid #e2e8f0;
    border-radius: 16px;
    padding: 24px;
    text-align: center;
    position: relative;
    overflow: hidden;
}

.score-display::before {
    content: '';
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: radial-gradient(circle, rgba(99, 102, 241, 0.05) 0%, transparent 70%);
    animation: pulse 3s ease-in-out infinite;
}

/* Barre de progression moderne */
.reliability-bar {
    height: 12px;
    background: #e2e8f0;
    border-radius: 10px;
    overflow: hidden;
    position: relative;
}

.reliability-fill {
    height: 100%;
    background: linear-gradient(90deg, #6366f1 0%, #8b5cf6 100%);
    border-radius: 10px;
    transition: width 1.5s cubic-bezier(0.4, 0, 0.2, 1);
    box-shadow: 0 0 20px rgba(99, 102, 241, 0.4);
}

/* Boutons modernes */
.modern-btn {
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
    border: none;
    border-radius: 14px;
    padding: 14px 32px;
    color: white;
    font-weight: 600;
    font-size: 0.95rem;
    letter-spacing: 0.3px;
    transition: all 0.3s ease;
    box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
    cursor: pointer;
}

.modern-btn:hover {
    transform: translateY(-3px);
    box-shadow: 0 8px 24px rgba(99, 102, 241, 0.4);
}

.modern-btn:active {
    transform: translateY(-1px);
}

/* Input moderne */
.modern-input {
    background: white;
    border: 2px solid #e2e8f0;
    border-radius: 14px;
    padding: 14px 18px;
    color: #0f172a;
    font-size: 0.95rem;
    transition: all 0.3s ease;
}

.modern-input:focus {
    outline: none;
    border-color: #6366f1;
    box-shadow: 0 0 0 4px rgba(99, 102, 241, 0.1);
}

/* Section headers */
.section-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 2px solid #e2e8f0;
}

.section-header h3 {
    color: #0f172a;
    font-weight: 700;
    font-size: 1.5rem;
    margin: 0;
}

.section-header i {
    color: #6366f1;
    font-size: 1.8rem;
}

/* Navbar moderne */
.modern-navbar {
    background: white;
    border-bottom: 1px solid #e2e8f0;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
    position: sticky;
    top: 0;
    z-index: 1000;
    backdrop-filter: blur(10px);
}

/* Graphiques */
.chart-wrapper {
    background: white;
    border-radius: 20px;
    border: 1px solid #e2e8f0;
    padding: 24px;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
}

/* Badge secteur */
.sector-badge-new {
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.1) 0%, rgba(139, 92, 246, 0.1) 100%);
    border: 1px solid rgba(99, 102, 241, 0.2);
    color: #4f46e5;
    padding: 6px 16px;
    border-radius: 20px;
    font-size: 0.85rem;
    font-weight: 600;
    display: inline-block;
}

/* Texte gradient */
.gradient-text {
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}

/* Alert moderne */
.modern-alert {
    background: linear-gradient(135deg, #eff6ff 0%, #f0f4ff 100%);
    border: 1px solid #cbd5e1;
    border-left: 4px solid #6366f1;
    border-radius: 14px;
    padding: 16px 20px;
    color: #0f172a;
}

/* Scrollbar */
::-webkit-scrollbar {
    width: 10px;
    height: 10px;
}

::-webkit-scrollbar-track {
    background: #f1f5f9;
}

::-webkit-scrollbar-thumb {
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
    border-radius: 10px;
}

::-webkit-scrollbar-thumb:hover {
    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
}

/* Animations */
.fade-in { animation: fadeInUp 0.6s ease-out; }
.fade-in-delay-1 { animation: fadeInUp 0.6s ease-out 0.1s both; }
.fade-in-delay-2 { animation: fadeInUp 0.6s ease-out 0.2s both; }
.fade-in-delay-3 { animation: fadeInUp 0.6s ease-out 0.3s both; }
.fade-in-delay-4 { animation: fadeInUp 0.6s ease-out 0.4s both; }

/* Dropdown moderne */
.Select-control {
    border: 2px solid #e2e8f0 !important;
    border-radius: 14px !important;
    background: white !important;
}

.Select-control:hover {
    border-color: #cbd5e1 !important;
}

/* Fix z-index pour dropdown */
.dash-dropdown {
    z-index: 9999 !important;
}

.dash-dropdown .Select-menu-outer {
    z-index: 9999 !important;
}

.dash-dropdown .dropdown {
    z-index: 9999 !important;
}

.dash-dropdown .dropdown-menu {
    z-index: 9999 !important;
}

/* Responsive */
@media (max-width: 768px) {
    .modern-card {
        padding: 20px;
    }
    
    .upload-zone {
        padding: 40px 20px;
    }
    
    .section-header h3 {
        font-size: 1.25rem;
    }
}
"""

# ============================================================================
# FONCTIONS UTILITAIRES - FALLBACK MODE SIMULATION
# ============================================================================

def parse_document_text(contents, filename):
    """Parse le contenu du document uploadé"""
    return parse_any_format(contents, filename)

def analyze_regulatory_impact(text):
    """
    Analyse le texte réglementaire et génère des scores d'impact pour chaque secteur/entreprise
    MODE SIMULATION - Utilisé si Bedrock n'est pas disponible
    """
    # Simulation d'analyse - Dans la vraie version, utiliser AWS Bedrock
    np.random.seed(hash(text) % 2**32)
    
    companies = {
        'AAPL': ('Apple Inc.', 'Technologie'),
        'MSFT': ('Microsoft Corp.', 'Technologie'),
        'GOOGL': ('Alphabet Inc.', 'Technologie'),
        'AMZN': ('Amazon.com Inc.', 'Commerce'),
        'NVDA': ('NVIDIA Corp.', 'Semi-conducteurs'),
        'TSLA': ('Tesla Inc.', 'Automobile'),
        'META': ('Meta Platforms', 'Médias Sociaux'),
        'JPM': ('JPMorgan Chase', 'Finance'),
        'V': ('Visa Inc.', 'Services Financiers'),
        'UNH': ('UnitedHealth', 'Santé'),
        'JNJ': ('Johnson & Johnson', 'Santé'),
        'PG': ('Procter & Gamble', 'Biens de consommation'),
        'HD': ('Home Depot', 'Commerce'),
        'MA': ('Mastercard', 'Services Financiers'),
        'PFE': ('Pfizer Inc.', 'Pharmacie'),
        'DIS': ('Walt Disney', 'Divertissement'),
        'BAC': ('Bank of America', 'Banque'),
        'XOM': ('Exxon Mobil', 'Énergie'),
        'CVX': ('Chevron Corp.', 'Énergie'),
        'INTC': ('Intel Corp.', 'Semi-conducteurs')
    }
    
    # Détection de mots-clés pour orienter l'analyse
    keywords = {
        'technologie': ['ai', 'intelligence artificielle', 'numérique', 'digital', 'data'],
        'finance': ['bancaire', 'financier', 'capital', 'crédit', 'bâle'],
        'énergie': ['carbone', 'émissions', 'climat', 'esg', 'environnement'],
        'santé': ['santé', 'médical', 'pharmaceutique', 'médicament']
    }
    
    text_lower = text.lower()
    sector_impacts = {}
    
    for sector, words in keywords.items():
        if any(word in text_lower for word in words):
            # Impact négatif si régulation stricte
            if any(term in text_lower for term in ['interdiction', 'restriction', 'obligation', 'sanction']):
                sector_impacts[sector] = np.random.uniform(-2.5, -0.5)
            else:
                sector_impacts[sector] = np.random.uniform(-1, 2)
        else:
            sector_impacts[sector] = np.random.uniform(-1, 1)
    
    results = []
    for ticker, (name, sector) in companies.items():
        # Génération du score basé sur le secteur et le texte
        base_score = sector_impacts.get(sector.lower(), 0)
        noise = np.random.normal(0, 0.5)
        impact_score = np.clip(base_score + noise, -3, 3)
        
        sentiment = get_sentiment_from_score(impact_score)
        
        # Génération de raisons contextuelles
        if impact_score < -1:
            reasons = [
                f"Contraintes réglementaires significatives pour le secteur {sector}",
                "Coûts de mise en conformité élevés anticipés",
                "Impact négatif potentiel sur les marges opérationnelles"
            ]
        elif impact_score < 0:
            reasons = [
                f"Ajustements nécessaires dans les opérations {sector}",
                "Délais de conformité à respecter",
                "Investissements requis pour l'adaptation"
            ]
        elif impact_score < 1:
            reasons = [
                "Impact limité sur les opérations courantes",
                "Période d'adaptation prévue dans la régulation",
                "Équilibre entre contraintes et opportunités"
            ]
        elif impact_score < 2:
            reasons = [
                f"Opportunités de croissance dans le secteur {sector}",
                "Avantages concurrentiels pour les acteurs conformes",
                "Incitations et subventions disponibles"
            ]
        else:
            reasons = [
                f"Catalyseur majeur pour le secteur {sector}",
                "Position de leadership renforcée",
                "Barrières à l'entrée favorables aux incumbents"
            ]
        
        results.append({
            'ticker': ticker,
            'company_name': name,
            'sector': sector,
            'impact_score': round(impact_score, 2),
            'sentiment': sentiment,
            'reliability': round(np.random.uniform(0.7, 0.95), 2),
            'reasons': reasons[:2],
            'date_analyzed': datetime.now().strftime('%Y-%m-%d %H:%M')
        })
    
    return pd.DataFrame(results)

def create_sector_analysis_card(sector_name, companies_data):
    """Crée une carte d'analyse large pour un secteur"""
    # Filtrer les neutres
    companies_data = companies_data[companies_data['sentiment'] != 'NEUTRAL']
    
    if len(companies_data) == 0:
        return html.Div()  # Ne pas afficher si aucune entreprise non-neutre
    
    avg_score = companies_data['impact_score'].mean()
    sentiment = get_sentiment_from_score(avg_score)
    sentiment_config = SENTIMENT_CONFIG[sentiment]
    
    companies_count = len(companies_data)
    
    return html.Div([
        html.Div([
            # En-tête du secteur
            html.Div([
                html.Div([
                    html.H4(sector_name, 
                           style={
                               'color': COLORS['text_primary'],
                               'fontWeight': '700',
                               'marginBottom': '4px',
                               'fontSize': '1.3rem'
                           }),
                    html.P(f"{companies_count} entreprise(s) analysée(s)",
                          style={
                              'color': COLORS['text_secondary'],
                              'fontSize': '0.9rem',
                              'marginBottom': '0'
                          })
                ], style={'flex': '1'}),
                
                # Sentiment badge
                html.Div([
                    html.Span([
                        html.I(className=sentiment_config['emoji'], 
                               style={'fontSize': '1.2rem', 'marginRight': '8px'}),
                        sentiment_config['label']
                    ], className='sentiment-badge',
                       style={
                           'background': f"{sentiment_config['color']}15",
                           'color': sentiment_config['color'],
                           'border': f"2px solid {sentiment_config['color']}30"
                       })
                ])
            ], style={
                'display': 'flex',
                'justifyContent': 'space-between',
                'alignItems': 'center',
                'marginBottom': '20px'
            }),
            
            # Score moyen
            html.Div([
                html.Div([
                    html.Span("IMPACT MOYEN", 
                             style={
                                 'fontSize': '0.75rem',
                                 'fontWeight': '600',
                                 'color': COLORS['text_secondary'],
                                 'letterSpacing': '1px'
                             }),
                    html.H2(f"{avg_score:+.2f}",
                           style={
                               'color': sentiment_config['color'],
                               'fontSize': '2.5rem',
                               'fontWeight': '800',
                               'marginTop': '8px',
                               'marginBottom': '0'
                           })
                ], className='score-display', style={'flex': '1', 'marginRight': '20px'}),
                
                # Statistiques
                html.Div([
                    html.Div([
                        html.Div([
                            html.I(className="fas fa-arrow-up",
                                  style={'color': COLORS['success'], 'marginRight': '8px'}),
                            html.Span(f"{len(companies_data[companies_data['impact_score'] > 0])} positif(s)",
                                     style={'color': COLORS['text_primary'], 'fontWeight': '500'})
                        ], style={'marginBottom': '8px'}),
                        html.Div([
                            html.I(className="fas fa-minus",
                                  style={'color': COLORS['text_secondary'], 'marginRight': '8px'}),
                            html.Span(f"{len(companies_data[abs(companies_data['impact_score']) <= 0.5])} neutre(s)",
                                     style={'color': COLORS['text_primary'], 'fontWeight': '500'})
                        ], style={'marginBottom': '8px'}),
                        html.Div([
                            html.I(className="fas fa-arrow-down",
                                  style={'color': COLORS['danger'], 'marginRight': '8px'}),
                            html.Span(f"{len(companies_data[companies_data['impact_score'] < 0])} négatif(s)",
                                     style={'color': COLORS['text_primary'], 'fontWeight': '500'})
                        ])
                    ], style={
                        'background': COLORS['surface_dark'],
                        'padding': '20px',
                        'borderRadius': '12px',
                        'border': f"1px solid {COLORS['border']}"
                    })
                ], style={'flex': '1'})
            ], style={'display': 'flex', 'gap': '20px'})
        ])
    ], className='sector-card')

def create_company_card_new(row):
    """Crée une carte d'entreprise moderne avec sentiment"""
    sentiment_config = SENTIMENT_CONFIG[row['sentiment']]
    
    return html.Div([
        html.Div([
            # En-tête
            html.Div([
                html.H4(row['ticker'],
                       style={
                           'color': COLORS['text_primary'],
                           'fontWeight': '800',
                           'fontSize': '1.5rem',
                           'marginBottom': '4px'
                       }),
                html.P(row['company_name'],
                      style={
                          'color': COLORS['text_secondary'],
                          'fontSize': '0.85rem',
                          'marginBottom': '12px'
                      })
            ]),
            
            # Badge secteur
            html.Div([
                html.Span(row['sector'], className='sector-badge-new')
            ], style={'marginBottom': '20px'}),
            
            # Sentiment avec icône
            html.Div([
                html.Div([
                    html.I(className=sentiment_config['emoji'],
                           style={'fontSize': '2.5rem', 'marginBottom': '12px', 'color': sentiment_config['color']}),
                    html.H5(sentiment_config['label'],
                           style={
                               'color': sentiment_config['color'],
                               'fontWeight': '700',
                               'marginBottom': '4px'
                           }),
                    html.Span(f"Score: {row['impact_score']:+.2f}",
                             style={
                                 'color': COLORS['text_secondary'],
                                 'fontSize': '0.85rem'
                             })
                ], style={
                    'textAlign': 'center',
                    'padding': '20px',
                    'background': f"{sentiment_config['color']}08",
                    'border': f"2px solid {sentiment_config['color']}30",
                    'borderRadius': '16px',
                    'marginBottom': '20px'
                })
            ]),
            
            # Fiabilité de l'analyse
            html.Div([
                html.Div([
                    html.Span("Fiabilité de l'analyse",
                             style={
                                 'fontSize': '0.8rem',
                                 'color': COLORS['text_secondary'],
                                 'fontWeight': '500'
                             }),
                    html.Span(f"{row['reliability']*100:.0f}%",
                             style={
                                 'fontSize': '0.9rem',
                                 'color': COLORS['text_primary'],
                                 'fontWeight': '700'
                             })
                ], style={
                    'display': 'flex',
                    'justifyContent': 'space-between',
                    'marginBottom': '8px'
                }),
                html.Div([
                    html.Div(className='reliability-fill',
                            style={'width': f"{row['reliability']*100}%"})
                ], className='reliability-bar')
            ], style={'marginBottom': '20px'}),
            
            # Raisons
            html.Div([
                html.H6("Points clés de l'analyse",
                       style={
                           'color': COLORS['text_primary'],
                           'fontWeight': '600',
                           'fontSize': '0.9rem',
                           'marginBottom': '12px'
                       }),
                html.Div([
                    html.Div([
                        html.I(className="fas fa-circle",
                              style={
                                  'color': sentiment_config['color'],
                                  'fontSize': '6px',
                                  'marginRight': '10px',
                                  'marginTop': '6px'
                              }),
                        html.Span(reason,
                                 style={
                                     'color': COLORS['text_secondary'],
                                     'fontSize': '0.85rem',
                                     'lineHeight': '1.6'
                                 })
                    ], style={
                        'display': 'flex',
                        'alignItems': 'flex-start',
                        'marginBottom': '8px'
                    })
                    for reason in row['reasons']
                ])
            ])
        ])
    ], className='company-card-new')

# ============================================================================
# LAYOUT - COMPOSANTS
# ============================================================================

# Navbar
navbar = html.Div([
    dbc.Container([
        html.Div([
            html.Div([
                html.I(className="fas fa-chart-line",
                      style={
                          'fontSize': '1.8rem',
                          'background': GRADIENTS['primary'],
                          'WebkitBackgroundClip': 'text',
                          'WebkitTextFillColor': 'transparent',
                          'marginRight': '12px',
                          'animation': 'pulse 2s ease-in-out infinite'
                      }),
                html.Div([
                    html.H3("PolicyPulse",
                           className='gradient-text',
                           style={'marginBottom': '0', 'fontSize': '1.5rem', 'fontWeight': '800', 'animation': 'pulse 2s ease-in-out infinite'}),
                    html.Small("Analyse d'Impact Réglementaire",
                              style={'color': COLORS['text_secondary'], 'fontSize': '0.75rem'})
                ])
            ], style={'display': 'flex', 'alignItems': 'center'}),
            
            html.Div([
                html.Div([
                    html.I(className="fas fa-user-circle", 
                          style={'fontSize': '2rem', 'color': COLORS['primary'], 'marginRight': '15px'})
                ], style={'display': 'flex', 'alignItems': 'center'}),
                html.Button([
                    html.I(className="fas fa-download", style={'marginRight': '8px'}),
                    "Exporter"
                ], id='export-btn', className='modern-btn',
                   style={'padding': '10px 24px', 'fontSize': '0.9rem'})
            ], style={'display': 'flex', 'alignItems': 'center'})
        ], style={
            'display': 'flex',
            'justifyContent': 'space-between',
            'alignItems': 'center',
            'padding': '20px 0'
        })
    ], fluid=True)
], className='modern-navbar')

# Section Upload
upload_section = dbc.Container([
    html.Div([
        dcc.Upload(
            id='upload-document',
            children=html.Div([
                html.I(className="fas fa-cloud-upload-alt",
                      style={'fontSize': '3.5rem', 'color': COLORS['primary'], 'marginBottom': '16px'}),
                html.H4("Déposez ou cliquez pour uploader un document",
                       style={'color': COLORS['text_primary'], 'fontWeight': '600', 'marginBottom': '8px'}),
                html.P("Formats acceptés : HTML, XML | Taille max : 10 MB",
                      style={'color': COLORS['text_secondary'], 'fontSize': '0.9rem', 'marginBottom': '0'})
            ]),
            className='upload-zone',
            multiple=False
        ),
        html.Div(id='upload-status', style={'marginTop': '20px'})
    ], className='modern-card fade-in')
], fluid=True, style={'marginTop': '30px', 'marginBottom': '30px'})

# Section Filtres
filters_section = dbc.Container([
    html.Div([
        html.Div([
            html.I(className="fas fa-filter"),
            html.H5("Filtres", style={'display': 'inline', 'margin': '0', 'marginLeft': '10px'})
        ], className='section-header'),
        
        dbc.Row([
            dbc.Col([
                html.Label("Rechercher une entreprise",
                          style={'color': COLORS['text_secondary'], 'fontSize': '0.85rem', 'fontWeight': '500', 'marginBottom': '8px'}),
                dbc.Input(
                    id='search-company',
                    type='text',
                    placeholder='Ticker ou nom...',
                    className='modern-input'
                )
            ], md=6),
            dbc.Col([
                html.Label("Filtrer par secteur",
                          style={'color': COLORS['text_secondary'], 'fontSize': '0.85rem', 'fontWeight': '500', 'marginBottom': '8px'}),
                html.Div([
                    dcc.Dropdown(
                        id='filter-sector',
                        options=[],
                        value='all',
                        placeholder="Tous les secteurs",
                        clearable=False
                    )
                ], style={'position': 'relative', 'zIndex': '10000'})
            ], md=6)
        ])
    ], className='modern-card fade-in-delay-1')
], fluid=True, style={'marginBottom': '30px', 'display': 'none'}, id='filters-container')

# Section Analyse par Secteur (LARGE)
sector_analysis_section = dbc.Container([
    html.Div([
        html.Div([
            html.Div([
                html.I(className="fas fa-layer-group"),
                html.H3("Analyse par Secteur")
            ], style={'display': 'flex', 'alignItems': 'center', 'gap': '12px', 'flex': '1'}),
            html.Button([
                html.I(id='sector-toggle-icon', className="fas fa-chevron-up")
            ], id='sector-toggle-btn', 
               style={
                   'background': 'none',
                   'border': 'none',
                   'color': COLORS['primary'],
                   'fontSize': '1.2rem',
                   'cursor': 'pointer',
                   'padding': '8px'
               })
        ], style={
            'display': 'flex',
            'justifyContent': 'space-between',
            'alignItems': 'center',
            'marginBottom': '24px',
            'paddingBottom': '16px',
            'borderBottom': f"2px solid {COLORS['border']}"
        }),
        
        html.Div(id='sector-analysis-content', style={'display': 'block'}, className='sector-content')
    ], className='modern-card fade-in-delay-2')
], fluid=True, style={'marginBottom': '30px', 'display': 'none'}, id='sector-container')

# Section Analyse par Entreprise (LARGE)
company_analysis_section = dbc.Container([
    html.Div([
        html.Div([
            html.I(className="fas fa-building"),
            html.H3("Analyse par Entreprise")
        ], className='section-header'),
        
        html.Div(id='filter-stats', style={'marginBottom': '20px'}),
        html.Div(id='companies-grid')
    ], className='modern-card fade-in-delay-3')
], fluid=True, style={'marginBottom': '30px', 'display': 'none'}, id='company-container')

# Section Graphiques (secondaire)
charts_section = dbc.Container([
    dbc.Row([
        dbc.Col([
            html.Div([
                html.H5("Distribution des Sentiments",
                       style={'color': COLORS['text_primary'], 'fontWeight': '600', 'marginBottom': '16px'}),
                dcc.Graph(id='sentiment-distribution', config={'displayModeBar': False})
            ], className='chart-wrapper')
        ], md=6, className='mb-4 fade-in-delay-4'),
        dbc.Col([
            html.Div([
                html.H5("Impacts par Secteur",
                       style={'color': COLORS['text_primary'], 'fontWeight': '600', 'marginBottom': '16px'}),
                dcc.Graph(id='sector-chart', config={'displayModeBar': False})
            ], className='chart-wrapper')
        ], md=6, className='mb-4 fade-in-delay-4')
    ])
], fluid=True, id='charts-container', style={'display': 'none'})

# Modal export
export_modal = dbc.Modal([
    dbc.ModalHeader("Exporter l'analyse"),
    dbc.ModalBody([
        html.P("Sélectionnez le format d'export :", style={'marginBottom': '20px'}),
        html.Div([
            html.Button([
                html.I(className="fas fa-file-csv", style={'marginRight': '10px'}),
                "CSV"
            ], id='export-csv', className='modern-btn',
               style={'marginRight': '15px', 'background': GRADIENTS['success']}),
            html.Button([
                html.I(className="fas fa-file-pdf", style={'marginRight': '10px'}),
                "Rapport PDF"
            ], id='export-pdf', className='modern-btn',
               style={'background': GRADIENTS['danger']})
        ])
    ]),
    dbc.ModalFooter([
        html.Button("Fermer", id='close-export', className='modern-btn',
                   style={'background': GRADIENTS['info']})
    ])
], id='export-modal', is_open=False)

download_component = dcc.Download(id='download-data')

# Footer
footer = html.Div([
    html.Hr(style={'borderColor': COLORS['border'], 'margin': '40px 0 20px 0'}),
    dbc.Container([
        html.Div([
            html.I(className="fas fa-trophy", style={'color': COLORS['warning'], 'marginRight': '10px'}),
            html.Span("Datathon PolyFinances 2025", style={'marginRight': '30px', 'color': COLORS['text_secondary']}),
            html.I(className="fas fa-robot", style={'color': COLORS['primary'], 'marginRight': '10px'}),
            html.Span("Powered by AWS Bedrock & Claude Sonnet", style={'marginRight': '30px', 'color': COLORS['text_secondary']}),
            html.I(className="fas fa-copyright", style={'color': COLORS['text_secondary'], 'marginRight': '8px'}),
            html.Span("Équipe 25", style={'color': COLORS['text_secondary'], 'fontWeight': '500'})
        ], style={'textAlign': 'center'})
    ], fluid=True)
], style={'padding': '20px 0'})

# Store pour les données et progression
data_store = dcc.Store(id='analysis-data')
progress_store = dcc.Store(id='progress-data')
interval_component = dcc.Interval(id='progress-interval', interval=500, n_intervals=0, disabled=True)

# ============================================================================
# LAYOUT PRINCIPAL
# ============================================================================

# Add custom CSS to app
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
''' + CUSTOM_CSS + '''
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''

# Composant de loader avec progression
loader_section = dbc.Container([
    html.Div([
        html.Div([
            html.Div([
                html.I(className="fas fa-cog fa-spin",
                      style={
                          'fontSize': '3rem',
                          'color': COLORS['primary'],
                          'marginBottom': '20px'
                      }),
                html.H4("Analyse en cours...",
                       style={
                           'color': COLORS['text_primary'],
                           'fontWeight': '600',
                           'marginBottom': '10px'
                       }),
                html.P(id='progress-text',
                      children="Initialisation de l'analyse",
                      style={
                          'color': COLORS['text_secondary'],
                          'fontSize': '0.9rem',
                          'marginBottom': '20px'
                      }),
                
                # Barre de progression
                html.Div([
                    html.Div([
                        html.Div(id='progress-bar',
                                style={
                                    'width': '0%',
                                    'height': '100%',
                                    'background': GRADIENTS['primary'],
                                    'borderRadius': '10px',
                                    'transition': 'width 0.3s ease',
                                    'boxShadow': '0 0 20px rgba(99, 102, 241, 0.4)'
                                })
                    ], style={
                        'width': '100%',
                        'height': '12px',
                        'background': COLORS['border'],
                        'borderRadius': '10px',
                        'overflow': 'hidden',
                        'marginBottom': '10px'
                    }),
                    html.Div([
                        html.Span(id='progress-percentage', children="0%",
                                 style={
                                     'color': COLORS['primary'],
                                     'fontWeight': '600',
                                     'fontSize': '0.9rem'
                                 }),
                        html.Span(id='progress-count', children="0/0 entreprises",
                                 style={
                                     'color': COLORS['text_secondary'],
                                     'fontSize': '0.85rem'
                                 })
                    ], style={
                        'display': 'flex',
                        'justifyContent': 'space-between',
                        'alignItems': 'center'
                    })
                ], style={'width': '100%', 'maxWidth': '400px'}),
                
                # Étapes de progression
                html.Div([
                    html.Div([
                        html.I(id='step1-icon', className="fas fa-circle",
                              style={'color': COLORS['primary'], 'marginRight': '8px'}),
                        html.Span("Parsing du document", style={'fontSize': '0.85rem'})
                    ], id='step1', style={'marginBottom': '8px', 'color': COLORS['text_secondary']}),
                    html.Div([
                        html.I(id='step2-icon', className="fas fa-circle",
                              style={'color': COLORS['border'], 'marginRight': '8px'}),
                        html.Span("Validation réglementaire", style={'fontSize': '0.85rem'})
                    ], id='step2', style={'marginBottom': '8px', 'color': COLORS['text_secondary']}),
                    html.Div([
                        html.I(id='step3-icon', className="fas fa-circle",
                              style={'color': COLORS['border'], 'marginRight': '8px'}),
                        html.Span("Analyse des entreprises", style={'fontSize': '0.85rem'})
                    ], id='step3', style={'marginBottom': '8px', 'color': COLORS['text_secondary']}),
                    html.Div([
                        html.I(id='step4-icon', className="fas fa-circle",
                              style={'color': COLORS['border'], 'marginRight': '8px'}),
                        html.Span("Génération des résultats", style={'fontSize': '0.85rem'})
                    ], id='step4', style={'color': COLORS['text_secondary']})
                ], style={'marginTop': '20px', 'textAlign': 'left'})
            ], style={
                'textAlign': 'center',
                'padding': '40px',
                'background': 'white',
                'borderRadius': '20px',
                'border': f"1px solid {COLORS['border']}",
                'boxShadow': '0 8px 24px rgba(15, 23, 42, 0.1)'
            })
        ], style={
            'display': 'flex',
            'justifyContent': 'center',
            'alignItems': 'center',
            'minHeight': '400px'
        })
    ])
], fluid=True, id='loader-container', style={'display': 'none', 'marginTop': '50px'})

app.layout = html.Div([
    navbar,
    upload_section,
    loader_section,
    filters_section,
    sector_analysis_section,
    company_analysis_section,
    charts_section,
    export_modal,
    download_component,
    data_store,
    progress_store,
    interval_component,
    footer
], style={'fontFamily': 'Inter, sans-serif', 'background': COLORS['background'], 'minHeight': '100vh', 'paddingBottom': '40px'})

# ============================================================================
# CALLBACKS
# ============================================================================

@app.callback(
    [Output('upload-status', 'children'),
     Output('analysis-data', 'data'),
     Output('filters-container', 'style'),
     Output('sector-container', 'style'),
     Output('company-container', 'style'),
     Output('charts-container', 'style'),
     Output('filter-sector', 'options'),
     Output('loader-container', 'style'),
     Output('progress-data', 'data'),
     Output('progress-interval', 'disabled')],
    [Input('upload-document', 'contents')],
    [State('upload-document', 'filename')]
)
def process_upload(contents, filename):
    """Traite le document uploadé et génère l'analyse - AVEC BEDROCK SI DISPONIBLE"""
    if contents is None:
        return (
            no_update,
            None,
            {'display': 'none'},
            {'display': 'none'},
            {'display': 'none'},
            {'display': 'none'},
            [],
            {'display': 'none'},
            None,
            True
        )
    
    print(f"\n{'='*80}")
    
    print(f"{'='*80}")
    
    # Parse le document
    
    text = parse_document_text(contents, filename)
    
    
    # Valider que c'est un document réglementaire
    
    is_valid = validate_regulatory_document(text)
    
    
    if not is_valid:
        error_msg = html.Div([
            html.I(className="fas fa-exclamation-circle",
                  style={'color': COLORS['danger'], 'fontSize': '1.5rem', 'marginRight': '12px'}),
            html.Div([
                html.H6("Document non-réglementaire détecté",
                       style={'color': COLORS['text_primary'], 'fontWeight': '600', 'marginBottom': '4px'}),
                html.P("Le document uploadé ne semble pas contenir de contenu réglementaire. Veuillez uploader un document de régulation valide.",
                      style={'color': COLORS['text_secondary'], 'fontSize': '0.85rem', 'marginBottom': '0'})
            ])
        ], className='modern-alert', style={'display': 'flex', 'alignItems': 'center', 'borderLeft': f'4px solid {COLORS["danger"]}'})
        
        return (
            error_msg,
            None,
            {'display': 'none'},
            {'display': 'none'},
            {'display': 'none'},
            {'display': 'none'},
            [],
            {'display': 'none'},
            None,
            True
        )
    
    # Initialiser les données de progression
    progress_data = {
        'step': 'parsing',
        'completed': 0,
        'total': 0,
        'percentage': 0,
        'message': 'Parsing du document en cours...'
    }
    
    # ANALYSE AVEC BEDROCK SI DISPONIBLE, SINON SIMULATION
    
    
    if BEDROCK_AVAILABLE:
        try:
            
            
            # DEBUG: Vérifier si le fichier JSON existe
            current_dir = Path(__file__).parent
            json_path = current_dir.parent / "data" / "processed" / "company_10k_data.json"
            
            
            
            
            
            # Callback de progression
            def update_progress(completed, total):
                nonlocal progress_data
                progress_data.update({
                    'step': 'analyzing',
                    'completed': completed,
                    'total': total,
                    'percentage': int((completed / total) * 100) if total > 0 else 0,
                    'message': f'Analyse en cours: {completed}/{total} entreprises'
                })
            
            results_list = analyze_regulation_with_bedrock(text, filename, update_progress)
            
            
            
            if results_list and len(results_list) > 0:
                df_results = pd.DataFrame(results_list)
                mode_text = f"Analyse en temps réel ({len(results_list)} entreprises)"
                
            else:
                
                
                df_results = analyze_regulatory_impact(text)
                mode_text = "⚠️ Mode simulation (Bedrock sans résultats)"
                
        except Exception as e:
            
            import traceback
            traceback.print_exc()
            df_results = analyze_regulatory_impact(text)
            mode_text = f"⚠️ Mode simulation (erreur: {str(e)[:50]})"
            
    else:
        
        df_results = analyze_regulatory_impact(text)
        mode_text = "💡 Mode simulation"
        
    
    # Finaliser la progression
    progress_data.update({
        'step': 'completed',
        'completed': len(df_results),
        'total': len(df_results),
        'percentage': 100,
        'message': 'Analyse terminée avec succès !'
    })
    
    
    print(f"{'='*80}\n")
    
    # Prépare les options de secteurs
    sectors = sorted(df_results['sector'].unique())
    sector_options = [{'label': 'Tous les secteurs', 'value': 'all'}] + \
                     [{'label': s, 'value': s} for s in sectors]
    
    # Message de succès
    status = html.Div([
        html.I(className="fas fa-check-circle",
              style={'color': COLORS['success'], 'fontSize': '1.5rem', 'marginRight': '12px'}),
        html.Div([
            html.H6("Analyse terminée avec succès !",
                   style={'color': COLORS['text_primary'], 'fontWeight': '600', 'marginBottom': '4px'}),
            html.P(f"Document : {filename} | {len(df_results)} entreprises analysées | {mode_text}",
                  style={'color': COLORS['text_secondary'], 'fontSize': '0.85rem', 'marginBottom': '0'})
        ])
    ], className='modern-alert', style={'display': 'flex', 'alignItems': 'center'})
    
    return (
        status,
        df_results.to_dict('records'),
        {'display': 'block'},
        {'display': 'block'},
        {'display': 'block'},
        {'display': 'block'},
        sector_options,
        {'display': 'none'},  # Masquer le loader
        progress_data,
        True  # Désactiver l'interval
    )

@app.callback(
    Output('sector-analysis-content', 'children'),
    [Input('analysis-data', 'data'),
     Input('filter-sector', 'value')]
)
def update_sector_analysis(data, selected_sector):
    """Met à jour l'analyse par secteur"""
    if not data:
        return html.Div()
    
    df = pd.DataFrame(data)
    
    # Filtrer les neutres
    df = df[df['sentiment'] != 'NEUTRAL']
    
    if selected_sector and selected_sector != 'all':
        df = df[df['sector'] == selected_sector]
    
    # Grouper par secteur
    sectors = df['sector'].unique()
    
    cards = []
    for sector in sorted(sectors):
        sector_data = df[df['sector'] == sector]
        cards.append(create_sector_analysis_card(sector, sector_data))
    
    return html.Div(cards)

@app.callback(
    [Output('filter-stats', 'children'),
     Output('companies-grid', 'children')],
    [Input('analysis-data', 'data'),
     Input('search-company', 'value'),
     Input('filter-sector', 'value')]
)
def update_companies_display(data, search, sector):
    """Met à jour l'affichage des entreprises"""
    if not data:
        return html.Div(), html.Div()
    
    df = pd.DataFrame(data)
    
    # Filtrer les neutres
    df = df[df['sentiment'] != 'NEUTRAL']
    
    # Filtres
    if search:
        mask = (df['ticker'].str.contains(search.upper(), na=False) | 
                df['company_name'].str.contains(search, case=False, na=False))
        df = df[mask]
    
    if sector and sector != 'all':
        df = df[df['sector'] == sector]
    
    # Stats
    stats = html.Div([
        html.I(className="fas fa-info-circle", style={'marginRight': '10px', 'color': COLORS['info']}),
        html.Span(f"Affichage de {len(df)} entreprise(s)",
                 style={'color': COLORS['text_primary'], 'fontWeight': '500'})
    ], className='modern-alert')
    
    # Grille de cartes
    if len(df) == 0:
        grid = html.Div([
            html.I(className="fas fa-search",
                  style={'fontSize': '3rem', 'color': COLORS['text_secondary'], 'marginBottom': '16px', 'opacity': '0.5'}),
            html.H5("Aucune entreprise trouvée", style={'color': COLORS['text_primary']}),
            html.P("Essayez d'ajuster vos filtres", style={'color': COLORS['text_secondary']})
        ], style={'textAlign': 'center', 'padding': '60px 0'})
    else:
        cards = []
        for _, row in df.iterrows():
            cards.append(
                dbc.Col([
                    create_company_card_new(row)
                ], md=6, lg=4, className='mb-4')
            )
        grid = dbc.Row(cards)
    
    return stats, grid

@app.callback(
    Output('sentiment-distribution', 'figure'),
    [Input('analysis-data', 'data')]
)
def update_sentiment_chart(data):
    """Graphique de distribution des sentiments"""
    if not data:
        return go.Figure()
    
    df = pd.DataFrame(data)
    
    sentiment_counts = df['sentiment'].value_counts()
    
    labels = [SENTIMENT_CONFIG[s]['label'] for s in sentiment_counts.index]
    colors = [SENTIMENT_CONFIG[s]['color'] for s in sentiment_counts.index]
    
    fig = go.Figure(data=[go.Bar(
        x=labels,
        y=sentiment_counts.values,
        marker=dict(
            color=colors,
            line=dict(width=0)
        ),
        text=sentiment_counts.values,
        textposition='outside',
        hovertemplate='%{x}<br>Nombre: %{y}<extra></extra>'
    )])
    
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(family='Inter', color=COLORS['text_primary']),
        xaxis=dict(
            showgrid=False,
            showline=False
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=COLORS['border'],
            showline=False
        ),
        margin=dict(l=20, r=20, t=20, b=20),
        showlegend=False,
        height=300
    )
    
    return fig

@app.callback(
    Output('sector-chart', 'figure'),
    [Input('analysis-data', 'data')]
)
def update_sector_chart(data):
    """Graphique des impacts par secteur"""
    if not data:
        return go.Figure()
    
    df = pd.DataFrame(data)
    
    sector_avg = df.groupby('sector')['impact_score'].mean().sort_values()
    
    colors = [COLORS['danger'] if x < 0 else COLORS['success'] for x in sector_avg.values]
    
    fig = go.Figure(data=[go.Bar(
        y=sector_avg.index,
        x=sector_avg.values,
        orientation='h',
        marker=dict(
            color=colors,
            line=dict(width=0)
        ),
        text=[f"{x:+.2f}" for x in sector_avg.values],
        textposition='outside',
        hovertemplate='%{y}<br>Impact moyen: %{x:.2f}<extra></extra>'
    )])
    
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(family='Inter', color=COLORS['text_primary']),
        xaxis=dict(
            showgrid=True,
            gridcolor=COLORS['border'],
            zeroline=True,
            zerolinecolor=COLORS['text_secondary']
        ),
        yaxis=dict(
            showgrid=False
        ),
        margin=dict(l=150, r=20, t=20, b=40),
        showlegend=False,
        height=400
    )
    
    return fig

@app.callback(
    [Output('sector-analysis-content', 'style'),
     Output('sector-toggle-icon', 'className')],
    [Input('sector-toggle-btn', 'n_clicks')],
    [State('sector-analysis-content', 'style')]
)
def toggle_sector_content(n_clicks, current_style):
    """Toggle l'affichage du contenu de l'analyse par secteur"""
    if n_clicks is None:
        return {'display': 'block'}, 'fas fa-chevron-up'
    
    if current_style and current_style.get('display') == 'none':
        return {'display': 'block'}, 'fas fa-chevron-up'
    else:
        return {'display': 'none'}, 'fas fa-chevron-down'

@app.callback(
    Output('export-modal', 'is_open'),
    [Input('export-btn', 'n_clicks'),
     Input('close-export', 'n_clicks')],
    [State('export-modal', 'is_open')]
)
def toggle_export_modal(n1, n2, is_open):
    """Toggle modal d'export"""
    if n1 or n2:
        return not is_open
    return is_open

@app.callback(
    Output('download-data', 'data'),
    [Input('export-csv', 'n_clicks'),
     Input('export-pdf', 'n_clicks')],
    [State('analysis-data', 'data')],
    prevent_initial_call=True
)
def export_data(csv_clicks, pdf_clicks, data):
    """Exporte les données"""
    if not data:
        raise PreventUpdate
    
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    df = pd.DataFrame(data)
    
    if button_id == 'export-csv':
        return dcc.send_data_frame(
            df.to_csv,
            filename=f"policypulse_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            index=False
        )
    elif button_id == 'export-pdf':
        # Génération HTML pour PDF
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Inter, sans-serif; color: #0f172a; }}
                h1 {{ color: #6366f1; font-weight: 800; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #e2e8f0; }}
                th {{ background: #6366f1; color: white; font-weight: 600; }}
            </style>
        </head>
        <body>
            <h1>PolicyPulse - Rapport d'Analyse Réglementaire</h1>
            <p>Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
            <table>
                <tr>
                    <th>Ticker</th>
                    <th>Entreprise</th>
                    <th>Secteur</th>
                    <th>Sentiment</th>
                    <th>Score</th>
                </tr>
        """
        
        for _, row in df.iterrows():
            sentiment_label = SENTIMENT_CONFIG[row['sentiment']]['label']
            html_content += f"""
                <tr>
                    <td><strong>{row['ticker']}</strong></td>
                    <td>{row['company_name']}</td>
                    <td>{row['sector']}</td>
                    <td>{sentiment_label}</td>
                    <td>{row['impact_score']:+.2f}</td>
                </tr>
            """
        
        html_content += """
            </table>
        </body>
        </html>
        """
        
        return dict(
            content=html_content,
            filename=f"policypulse_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        )
    
    raise PreventUpdate

@app.callback(
    [Output('progress-text', 'children'),
     Output('progress-bar', 'style'),
     Output('progress-percentage', 'children'),
     Output('progress-count', 'children'),
     Output('step1-icon', 'className'),
     Output('step1', 'style'),
     Output('step2-icon', 'className'),
     Output('step2', 'style'),
     Output('step3-icon', 'className'),
     Output('step3', 'style'),
     Output('step4-icon', 'className'),
     Output('step4', 'style')],
    [Input('progress-interval', 'n_intervals')],
    [State('progress-data', 'data')]
)
def update_progress_display(n_intervals, progress_data):
    """Met à jour l'affichage de la progression"""
    if not progress_data:
        return (
            "Initialisation...",
            {'width': '0%', 'height': '100%', 'background': GRADIENTS['primary'], 'borderRadius': '10px', 'transition': 'width 0.3s ease', 'boxShadow': '0 0 20px rgba(99, 102, 241, 0.4)'},
            "0%",
            "0/0 entreprises",
            "fas fa-circle", {'marginBottom': '8px', 'color': COLORS['text_secondary']},
            "fas fa-circle", {'marginBottom': '8px', 'color': COLORS['text_secondary']},
            "fas fa-circle", {'marginBottom': '8px', 'color': COLORS['text_secondary']},
            "fas fa-circle", {'color': COLORS['text_secondary']}
        )
    
    step = progress_data.get('step', 'parsing')
    completed = progress_data.get('completed', 0)
    total = progress_data.get('total', 0)
    percentage = progress_data.get('percentage', 0)
    message = progress_data.get('message', 'En cours...')
    
    # Styles des étapes
    step_styles = {
        'active': {'marginBottom': '8px', 'color': COLORS['primary'], 'fontWeight': '600'},
        'completed': {'marginBottom': '8px', 'color': COLORS['success'], 'fontWeight': '500'},
        'pending': {'marginBottom': '8px', 'color': COLORS['text_secondary']}
    }
    
    step_icons = {
        'active': 'fas fa-spinner fa-spin',
        'completed': 'fas fa-check-circle',
        'pending': 'fas fa-circle'
    }
    
    # Déterminer l'état de chaque étape
    steps_status = {
        'step1': 'completed' if step in ['validation', 'analyzing', 'completed'] else ('active' if step == 'parsing' else 'pending'),
        'step2': 'completed' if step in ['analyzing', 'completed'] else ('active' if step == 'validation' else 'pending'),
        'step3': 'completed' if step == 'completed' else ('active' if step == 'analyzing' else 'pending'),
        'step4': 'completed' if step == 'completed' else 'pending'
    }
    
    return (
        message,
        {
            'width': f'{percentage}%',
            'height': '100%',
            'background': GRADIENTS['primary'],
            'borderRadius': '10px',
            'transition': 'width 0.3s ease',
            'boxShadow': '0 0 20px rgba(99, 102, 241, 0.4)'
        },
        f"{percentage}%",
        f"{completed}/{total} entreprises" if total > 0 else "Préparation...",
        step_icons[steps_status['step1']], step_styles[steps_status['step1']],
        step_icons[steps_status['step2']], step_styles[steps_status['step2']],
        step_icons[steps_status['step3']], step_styles[steps_status['step3']],
        step_icons[steps_status['step4']], step_styles[steps_status['step4']]
    )

@app.callback(
    Output('upload-document', 'disabled'),
    [Input('progress-data', 'data')]
)
def disable_upload_during_processing(progress_data):
    """Désactive l'upload pendant le traitement"""
    if progress_data and progress_data.get('step') not in [None, 'completed']:
        return True
    return False

@app.callback(
    [Output('loader-container', 'style', allow_duplicate=True),
     Output('progress-interval', 'disabled', allow_duplicate=True)],
    [Input('upload-document', 'contents')],
    prevent_initial_call=True
)
def show_loader_on_upload(contents):
    """Affiche le loader dès qu'un fichier est uploadé"""
    if contents:
        return {'display': 'block', 'marginTop': '50px'}, False
    return {'display': 'none'}, True

# ============================================================================
# LANCEMENT
# ============================================================================

if __name__ == '__main__':
    print("="*80)
    
    print("="*80)
    
    
    
    
    
    
    print()
    
    if BEDROCK_AVAILABLE:
        pass
    else:
        pass
    
    test_companies = load_company_data_from_json()
    if test_companies:
        pass
    else:
        pass
    
    app.run(debug=True, host='0.0.0.0', port=8050)