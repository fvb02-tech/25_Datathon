#!/usr/bin/env python3
"""
PIPELINE D'ANALYSE RÉGLEMENTAIRE - DATATHON POLYFINANCES 2025
Croise les régulations avec les données 10-K pour calculer les scores d'impact
"""

import boto3
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple
import time
from datetime import datetime
import pandas as pd
from tqdm import tqdm
import os

import sys

sys.path.append(str(Path(__file__).parent.parent))
from config import FILLINGS_DIR, PROJECT_DIR, PROCESSED_DIR, FILLINGS_DIR, AWS_REGION, MODEL_ID_10K

# ============================================================================
# CONFIGURATION
# ============================================================================

BEDROCK_CLIENT = boto3.client('bedrock-runtime', region_name=AWS_REGION)
MODEL_ID = MODEL_ID_10K

# Chemins des données
REGULATIONS_FILE = Path(os.path.join(PROCESSED_DIR, "regulatory_documents.json"))
COMPANY_10K_FILE = Path(os.path.join(PROCESSED_DIR,"company_10k_data.json"))
RISK_SCORES_FILE = Path("/home/sagemaker-user/shared/Law1_Risk_score_500_ok.json")
OUTPUT_FILE = Path("impact_analysis_results.json")
RECOMMENDATIONS_FILE = Path("recommendations.csv")

# Parallélisation
MAX_WORKERS = 5
MAX_RETRIES = 2

# ============================================================================
# PROMPT D'ANALYSE D'IMPACT
# ============================================================================

IMPACT_ANALYSIS_PROMPT = """You are a financial analyst evaluating regulatory impact on companies.

**REGULATION:**
Name: {regulation_name}
Jurisdiction: {jurisdiction}
Key Requirements: {requirements}
Penalties: {penalties}
Effective Date: {effective_date}

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
  "impact_score": <number from -2 to +2>,
  "impact_category": "<one of: STRONG_NEGATIVE, MODERATE_NEGATIVE, NEUTRAL, MODERATE_POSITIVE, STRONG_POSITIVE>",
  "confidence": <number from 0 to 1>,
  "key_reasons": ["reason 1", "reason 2", "reason 3"],
  "recommendation": "<one of: SELL, REDUCE, HOLD, BUY, STRONG_BUY>",
  "explanation": "<2-3 sentences explaining the score>"
}}

**SCORING GUIDE:**
- **-2 (STRONG_NEGATIVE)**: Severe negative impact, fundamental business model threat
- **-1 (MODERATE_NEGATIVE)**: Notable negative impact, adaptation required
- **0 (NEUTRAL)**: Minimal or balanced impact
- **+1 (MODERATE_POSITIVE)**: Notable competitive advantage or new opportunities
- **+2 (STRONG_POSITIVE)**: Major competitive advantage, strong growth catalyst

**CRITICAL:** Return ONLY the JSON object, no other text."""

# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================

def load_regulations() -> List[Dict]:
    """Charge les documents réglementaires"""
    with open(REGULATIONS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data

def load_company_data() -> List[Dict]:
    """Charge les données 10-K extraites"""
    with open(COMPANY_10K_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # Ne garder que les extractions réussies
    return [d for d in data if d.get('success', False)]

def load_risk_scores() -> Dict[str, Dict]:
    """Charge les scores de risque pré-calculés"""
    with open(RISK_SCORES_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # Indexer par ticker pour un accès rapide
    risk_by_ticker = {}
    for company in data:
        ticker = company.get('ticker')
        if ticker:
            risk_by_ticker[ticker] = company
    return risk_by_ticker

def format_company_info(company_data: Dict) -> Dict[str, str]:
    """Formate les informations de l'entreprise pour le prompt"""
    data = company_data.get('data', {})
    
    # Identity
    identity = data.get('identity_and_jurisdiction', {})
    company_name = identity.get('company_name', 'Unknown')
    ticker = company_data.get('ticker', 'UNK')
    sector = identity.get('sector_industry', 'Unknown')
    
    # Geography
    geo = data.get('geographic_exposure', {})
    geography_parts = []
    for region, key in [
        ('Americas', 'americas_revenue_share_prct_2024'),
        ('Europe', 'europe_revenue_share_prct_2024'),
        ('China', 'china_revenue_share_prct_2024'),
        ('Japan', 'japan_revenue_share_prct_2024'),
        ('Rest of Asia', 'restofasia_revenue_share_prct_2024')
    ]:
        value = geo.get(key)
        if value:
            geography_parts.append(f"{region}: {value}%")
    geography = ", ".join(geography_parts) if geography_parts else "Not disclosed"
    
    # Business mix
    biz = data.get('business_mix', {})
    business_parts = []
    if biz.get('goods_revenue_usd'):
        business_parts.append(f"Goods: ${biz['goods_revenue_usd']/1e9:.1f}B")
    if biz.get('services_revenue_usd'):
        business_parts.append(f"Services: ${biz['services_revenue_usd']/1e9:.1f}B")
    if biz.get('financial_revenue_usd'):
        business_parts.append(f"Financial: ${biz['financial_revenue_usd']/1e9:.1f}B")
    business_mix = ", ".join(business_parts) if business_parts else "Not disclosed"
    
    # Supply chain
    supply = data.get('supply_chain_and_commitments', {})
    suppliers = supply.get('suppliers_sector_industries', [])
    supply_chain = ", ".join(suppliers) if suppliers else "Not disclosed"
    
    # R&D
    tax_innov = data.get('tax_and_innovation', {})
    r_and_d_value = tax_innov.get('r_and_d_expense_usd')
    r_and_d = f"${r_and_d_value/1e9:.1f}B" if r_and_d_value else "Not disclosed"
    
    return {
        'company_name': company_name,
        'ticker': ticker,
        'sector': sector,
        'geography': geography,
        'business_mix': business_mix,
        'supply_chain': supply_chain,
        'r_and_d': r_and_d
    }

def call_bedrock(prompt: str) -> Optional[Dict]:
    """Appelle Bedrock pour l'analyse d'impact"""
    for attempt in range(MAX_RETRIES):
        try:
            response = BEDROCK_CLIENT.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2000,
                    "temperature": 0.1,
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": prompt}]
                        }
                    ]
                })
            )
            
            response_body = json.loads(response['body'].read())
            response_text = response_body['content'][0]['text']
            
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
        
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
                continue
            print(f"❌ Bedrock error: {e}")
            return None
    
    return None

def analyze_company_regulation_pair(
    company_data: Dict,
    regulation: Dict
) -> Optional[Dict]:
    """Analyse l'impact d'une régulation sur une entreprise"""
    
    company_info = format_company_info(company_data)
    ticker = company_data.get('ticker', 'UNK')
    
    # Créer le prompt
    prompt = IMPACT_ANALYSIS_PROMPT.format(
        regulation_name=regulation.get('title', 'Unknown'),
        jurisdiction=regulation.get('jurisdiction', 'Unknown'),
        requirements=regulation.get('key_requirements', 'Not specified'),
        penalties=regulation.get('penalties', 'Not specified'),
        effective_date=regulation.get('effective_date', 'Not specified'),
        **company_info
    )
    
    # Appeler Bedrock
    analysis = call_bedrock(prompt)
    
    if analysis:
        return {
            'ticker': ticker,
            'company_name': company_info['company_name'],
            'regulation_name': regulation.get('title', 'Unknown'),
            'regulation_jurisdiction': regulation.get('jurisdiction', 'Unknown'),
            'impact_score': analysis.get('impact_score', 0),
            'impact_category': analysis.get('impact_category', 'NEUTRAL'),
            'confidence': analysis.get('confidence', 0.5),
            'key_reasons': analysis.get('key_reasons', []),
            'recommendation': analysis.get('recommendation', 'HOLD'),
            'explanation': analysis.get('explanation', ''),
            'analyzed_at': datetime.now().isoformat()
        }
    
    return None

def run_full_analysis(sample_size: Optional[int] = None):
    """
    Exécute l'analyse complète en utilisant les scores pré-calculés
    
    Args:
        sample_size: Nombre d'entreprises à analyser (None = toutes)
    """
    print("🎯 ANALYSE D'IMPACT RÉGLEMENTAIRE (SCORES PRÉ-CALCULÉS)")
    print("=" * 70)
    
    # Charger les données
    print("📚 Chargement des données...")
    regulations = load_regulations()
    companies = load_company_data()
    risk_scores = load_risk_scores()
    
    if sample_size:
        companies = companies[:sample_size]
    
    print(f"📋 Régulations: {len(regulations)}")
    print(f"🏢 Entreprises: {len(companies)}")
    print(f"📊 Scores de risque disponibles: {len(risk_scores)}")
    print()
    
    # Traitement direct des scores
    results = []
    start_time = time.time()
    
    print("🔄 Traitement des scores pré-calculés...\n")
    
    for company in tqdm(companies, desc="Traitement"):
        ticker = company.get('ticker')
        if not ticker or ticker not in risk_scores:
            continue
            
        risk_data = risk_scores[ticker]
        company_info = format_company_info(company)
        
        # Pour chaque régulation, utiliser le score pré-calculé
        for regulation in regulations:
            result = {
                'ticker': ticker,
                'company_name': company_info['company_name'],
                'regulation_name': regulation.get('title', 'Unknown'),
                'regulation_jurisdiction': regulation.get('jurisdiction', 'Unknown'),
                'impact_score': risk_data.get('overall_impact_score', 0),
                'impact_category': risk_data.get('impact_category', 'NEUTRAL'),
                'confidence': 0.9,  # Score pré-calculé = haute confiance
                'key_reasons': risk_data.get('key_impact_factors', []),
                'recommendation': risk_data.get('investment_recommendation', 'HOLD'),
                'explanation': risk_data.get('detailed_analysis', ''),
                'analyzed_at': datetime.now().isoformat(),
                'source': 'pre_calculated'
            }
            results.append(result)
    
    elapsed_time = time.time() - start_time
    
    # Statistiques
    print()
    print("=" * 70)
    print("📊 STATISTIQUES")
    print("=" * 70)
    print(f"✅ Analyses réussies: {len(results)}/{len(tasks)}")
    print(f"⏱️  Temps total: {elapsed_time/60:.1f} minutes")
    print(f"⚡ Vitesse: {len(results)/elapsed_time*60:.1f} analyses/minute")
    
    # Sauvegarder les résultats complets
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Résultats sauvegardés: {OUTPUT_FILE}")
    
    # Créer un CSV de recommandations
    df = pd.DataFrame(results)
    
    # Agréger par entreprise (moyenne des scores)
    df_company_summary = df.groupby(['ticker', 'company_name']).agg({
        'impact_score': 'mean',
        'confidence': 'mean'
    }).reset_index()
    
    # Déterminer la recommandation globale
    def get_overall_recommendation(score):
        if score <= -1.5:
            return 'SELL'
        elif score <= -0.5:
            return 'REDUCE'
        elif score <= 0.5:
            return 'HOLD'
        elif score <= 1.5:
            return 'BUY'
        else:
            return 'STRONG_BUY'
    
    df_company_summary['overall_recommendation'] = df_company_summary['impact_score'].apply(
        get_overall_recommendation
    )
    
    df_company_summary = df_company_summary.sort_values('impact_score')
    df_company_summary.to_csv(RECOMMENDATIONS_FILE, index=False)
    
    print(f"📄 Recommandations CSV: {RECOMMENDATIONS_FILE}")
    
    # Afficher le top 10 positif et négatif
    print("\n🔴 TOP 10 IMPACTS NÉGATIFS:")
    print(df_company_summary.head(10)[['ticker', 'company_name', 'impact_score', 'overall_recommendation']])
    
    print("\n🟢 TOP 10 IMPACTS POSITIFS:")
    print(df_company_summary.tail(10)[['ticker', 'company_name', 'impact_score', 'overall_recommendation']])
    
    return results

# ============================================================================
# POINT D'ENTRÉE
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyse d'impact réglementaire")
    parser.add_argument('--sample', type=int, help='Nombre d\'entreprises à analyser (test)')
    parser.add_argument('--full', action='store_true', help='Analyser toutes les entreprises')
    
    args = parser.parse_args()
    
    if args.sample:
        print(f"📊 Mode échantillon: {args.sample} entreprises\n")
        run_full_analysis(sample_size=args.sample)
    elif args.full:
        print("🚀 Mode complet: toutes les entreprises\n")
        run_full_analysis()
    else:
        print("💡 Utilisez --sample N (test) ou --full (complet)")
        print("   Exemple: python run_analysis.py --sample 20\n")
        print("   Lancement avec 10 entreprises par défaut...\n")
        run_full_analysis(sample_size=10)