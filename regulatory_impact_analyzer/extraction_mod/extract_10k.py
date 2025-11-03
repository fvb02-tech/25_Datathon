"""
Extrait les données de 500 rapports 10-K en parallèle avec Bedrock
"""

import boto3
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional, List
import time
from datetime import datetime
from bs4 import BeautifulSoup
import pandas as pd
from tqdm import tqdm

import sys

sys.path.append(str(Path.cwd().parent))
from config import FILLINGS_DIR, PROJECT_DIR, PROCESSED_DIR, FILLINGS_DIR, AWS_REGION, MODEL_ID

from config import FILLINGS_DIR, PROJECT_DIR, PROCESSED_DIR, FILLINGS_DIR, AWS_REGION, MODEL_ID_10K

# ============================================================================
# CONFIGURATION
# ============================================================================

BEDROCK_CLIENT = boto3.client('bedrock-runtime', region_name=AWS_REGION)
MODEL_ID = MODEL_ID_10K

# Chemins

OUTPUT_FILE = Path(os.path.join(PROCESSED_DIR,"company_10k_data.json"))
ERROR_LOG_FILE = Path(os.path.join(PROCESSED_DIR,"extraction_errors.log"))

# Parallélisation
MAX_WORKERS = 5  # Respecter les rate limits Bedrock
MAX_RETRIES = 2
CHAR_LIMIT = 400000  # Limite pour Bedrock 

# ============================================================================
# SCHÉMA JSON ATTENDU
# ============================================================================

JSON_SCHEMA = {
    "identity_and_jurisdiction": {
        "company_name": "string",
        "trading_symbol": "string",
        "legal_domicile_country": "string",
        "sector_industry": "string"
    },
    "geographic_exposure": {
        "americas_revenue_share_prct_2024": "float or null",
        "europe_revenue_share_prct_2024": "float or null",
        "china_revenue_share_prct_2024": "float or null",
        "japan_revenue_share_prct_2024": "float or null",
        "restofasia_revenue_share_prct_2024": "float or null",
        "regions_of_activity": "string"
    },
    "business_mix": {
        "goods_revenue_usd": "float or null",
        "services_revenue_usd": "float or null",
        "financial_revenue_usd": "float or null"
    },
    "supply_chain_and_commitments": {
        "purchase_obligations_usd": "float or null",
        "suppliers_sector_industries": ["list of strings"]
    },
    "tax_and_innovation": {
        "r_and_d_expense_usd": "float or null"
    }
}

# ============================================================================
# PROMPT BEDROCK
# ============================================================================

EXTRACTION_PROMPT = """You are a financial analyst extracting structured data from 10-K filings.

**CRITICAL INSTRUCTIONS:**
1. Extract data EXACTLY as reported in the filing
2. Use null for missing values (except americas_revenue_share_prct_2024 which should be calculated)
3. Return ONLY a valid JSON object matching the schema below
4. Do NOT add any text before or after the JSON
5. Numbers should be in full USD (no commas, no abbreviations)
6. Percentages should be decimal values (e.g., 42.5 not 0.425)

**SCHEMA:**
{schema}

**10-K FILING CONTENT:**
{content}

**OUTPUT (JSON only):**"""

# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================

def extract_text_from_html(html_path: Path) -> str:
    """Extrait le texte d'un fichier HTML 10-K"""
    try:
        with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
            html_content = f.read()
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Retirer scripts et styles
        for script in soup(["script", "style"]):
            script.decompose()
        
        text = soup.get_text(separator='\n', strip=True)
        
        # Limiter la taille pour Bedrock
        if len(text) > CHAR_LIMIT:
            # Prendre le début (souvent plus important)
            text = text[:CHAR_LIMIT]
        
        return text
    
    except Exception as e:
        log_error(html_path.name, f"HTML extraction error: {e}")
        return ""

def call_bedrock(prompt: str, max_retries: int = MAX_RETRIES) -> Optional[Dict]:
    """Appelle Bedrock avec retry logic"""
    for attempt in range(max_retries):
        try:
            response = BEDROCK_CLIENT.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4000,
                    "temperature": 0.0,  # Extraction factuelle
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
            
            # Parser le JSON de la réponse
            # Nettoyer les markdown code blocks si présents
            response_text = response_text.strip()
            if response_text.startswith('```json'):
                response_text = response_text[7:]
            if response_text.startswith('```'):
                response_text = response_text[3:]
            if response_text.endswith('```'):
                response_text = response_text[:-3]
            
            data = json.loads(response_text.strip())
            return data
        
        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            log_error("bedrock_call", f"JSON decode error: {e}")
            return None
        
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            log_error("bedrock_call", f"Bedrock error: {e}")
            return None
    
    return None

def log_error(ticker: str, error_msg: str):
    """Log les erreurs dans un fichier"""
    timestamp = datetime.now().isoformat()
    with open(ERROR_LOG_FILE, 'a') as f:
        f.write(f"[{timestamp}] {ticker}: {error_msg}\n")

def process_single_10k(html_path: Path) -> Dict:
    """Traite un seul fichier 10-K"""
    ticker = html_path.parent.name
    
    try:
        # Extraire le texte
        text = extract_text_from_html(html_path)
        if not text:
            return {
                'ticker': ticker,
                'file_path': str(html_path),
                'success': False,
                'error': 'Empty text extraction'
            }
        
        # Créer le prompt
        prompt = EXTRACTION_PROMPT.format(
            schema=json.dumps(JSON_SCHEMA, indent=2),
            content=text
        )
        
        # Appeler Bedrock
        data = call_bedrock(prompt)
        
        if data:
            return {
                'ticker': ticker,
                'file_path': str(html_path),
                'success': True,
                'data': data,
                'extracted_at': datetime.now().isoformat()
            }
        else:
            return {
                'ticker': ticker,
                'file_path': str(html_path),
                'success': False,
                'error': 'Bedrock extraction failed'
            }
    
    except Exception as e:
        log_error(ticker, str(e))
        return {
            'ticker': ticker,
            'file_path': str(html_path),
            'success': False,
            'error': str(e)
        }

# ============================================================================
# FONCTION PRINCIPALE
# ============================================================================

def extract_all_10k(sample_size: Optional[int] = None, dry_run: bool = False):
    """
    Extrait les données de tous les 10-K
    
    Args:
        sample_size: Nombre de fichiers à traiter (None = tous)
        dry_run: Si True, traite seulement 5 fichiers pour tester
    """
    print(" EXTRACTION 10-K - DATATHON POLYFINANCES 2025")
    print("=" * 70)
    
    # Trouver tous les fichiers HTML
    all_files = []
    for ticker_dir in FILLINGS_DIR.iterdir():
        if ticker_dir.is_dir():
            html_files = list(ticker_dir.glob("*.html"))
            if html_files:
                all_files.append(html_files[0])  # Prendre le premier fichier
    
    print(f" Fichiers trouvés: {len(all_files)}")
    
    if dry_run:
        print("  MODE DRY RUN - Traitement de 5 fichiers seulement")
        all_files = all_files[:5]
    elif sample_size:
        print(f"📊 Mode échantillon: {sample_size} fichiers")
        all_files = all_files[:sample_size]
    
    print(f"🔄 Fichiers à traiter: {len(all_files)}")
    print(f"⚙️  Parallélisation: {MAX_WORKERS} workers")
    print()
    
    # Traitement parallèle
    results = []
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_single_10k, f): f for f in all_files}
        
        for future in tqdm(as_completed(futures), total=len(all_files), desc="Extraction"):
            result = future.result()
            results.append(result)
            
            # Petit délai pour respecter rate limits
            time.sleep(0.2)
    
    elapsed_time = time.time() - start_time
    
    # Statistiques
    successful = sum(1 for r in results if r['success'])
    failed = len(results) - successful
    
    print()
    print("=" * 70)
    print(" STATISTIQUES")
    print("=" * 70)
    print(f"✅ Succès: {successful}/{len(results)} ({successful/len(results)*100:.1f}%)")
    print(f"❌ Échecs: {failed}")
    print(f"⏱️  Temps total: {elapsed_time/60:.1f} minutes")
    print(f"⚡ Vitesse: {len(results)/elapsed_time*60:.1f} fichiers/minute")
    
    # Sauvegarder les résultats
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Résultats sauvegardés: {OUTPUT_FILE}")
    
    if failed > 0:
        print(f"⚠️  Erreurs logguées dans: {ERROR_LOG_FILE}")
    
    # Créer un CSV récapitulatif
    df_summary = pd.DataFrame([
        {
            'ticker': r['ticker'],
            'success': r['success'],
            'company_name': r['data']['identity_and_jurisdiction']['company_name'] if r['success'] else None,
            'sector': r['data']['identity_and_jurisdiction']['sector_industry'] if r['success'] else None
        }
        for r in results
    ])
    
    csv_file = OUTPUT_FILE.with_suffix('.csv')
    df_summary.to_csv(csv_file, index=False)
    print(f" Récapitulatif CSV: {csv_file}")
    
    return results

# ============================================================================
# POINT D'ENTRÉE
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Extraction robuste des 10-K")
    parser.add_argument('--dry-run', action='store_true', help='Tester sur 5 fichiers')
    parser.add_argument('--sample', type=int, help='Nombre de fichiers à traiter')
    parser.add_argument('--full', action='store_true', help='Traiter tous les 500 fichiers')
    
    args = parser.parse_args()
    
    if args.dry_run:
        extract_all_10k(dry_run=True)
    elif args.sample:
        extract_all_10k(sample_size=args.sample)
    elif args.full:
        extract_all_10k()
    else:
        # Par défaut: dry run
        print("💡 Utilisez --dry-run, --sample N, ou --full")
        print("   Lancement en mode dry-run par défaut...\n")
        extract_all_10k(dry_run=True)