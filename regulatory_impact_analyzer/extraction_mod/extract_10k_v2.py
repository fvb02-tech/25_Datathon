"""
Version flexible : s'adapte automatiquement aux données
"""

import boto3
import json
import os
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional
import time
from datetime import datetime
from bs4 import BeautifulSoup
import pandas as pd
from tqdm import tqdm

import sys

sys.path.append(str(Path.cwd().parent))
from config import FILLINGS_DIR, PROJECT_DIR, PROCESSED_DIR, FILLINGS_DIR, AWS_REGION, MODEL_ID

from config import FILLINGS_DIR, PROCESSED_DIR, AWS_REGION, MODEL_ID_10K

# ============================================================================
# CONFIGURATION
# ============================================================================

BEDROCK_CLIENT = boto3.client('bedrock-runtime', region_name=AWS_REGION)
MODEL_ID = MODEL_ID_10K

# Chemins
OUTPUT_FILE = Path(os.path.join(PROCESSED_DIR, "company_10k_data.json"))
ERROR_LOG_FILE = Path(os.path.join(PROCESSED_DIR, "extraction_errors.log"))

# Parallélisation
MAX_WORKERS = 5
MAX_RETRIES = 3
CHAR_LIMIT = 350000

# ============================================================================
# PROMPT GÉNÉRIQUE (IA S'ADAPTE AUX DONNÉES)
# ============================================================================

EXTRACTION_PROMPT = """You are a financial analyst extracting data from a 10-K filing.

**CRITICAL: Extract data EXACTLY AS REPORTED. Do NOT assume structure.**

Return a JSON object with FLEXIBLE structure that adapts to what you find:

{
    "company_info": {
        "name": "string",
        "ticker": "string", 
        "domicile_country": "string",
        "sector": "string"
    },
    
    "geographic_revenue": {
        // IMPORTANT: Use the EXACT region names from the document
        // DO NOT force specific regions like "Americas" or "Europe"
        // If company reports "North America", use "North America"
        // If company reports "EMEA", use "EMEA"
        // Return as key-value pairs: {"region_name": percentage}
        // Example: {"United States": 45.2, "China": 23.1, "Europe": 31.7}
    },
    
    "business_segments": {
        // Extract revenue by business line AS REPORTED
        // Use company's own segment names
        // Example: {"iPhone": 52.3, "Services": 24.1, "Mac": 10.2, "iPad": 8.5, "Wearables": 4.9}
        // OR: {"Products": 75.0, "Services": 25.0}
        // Adapt to what's in the document
    },
    
    "key_financials": {
        "total_revenue_usd": "float or null",
        "r_and_d_expense_usd": "float or null",
        "purchase_obligations_usd": "float or null"
    },
    
    "supply_chain": {
        "major_suppliers_industries": ["list of supplier industries if mentioned"],
        "key_supplier_countries": ["list of countries if mentioned"]
    },
    
    "metadata": {
        "fiscal_year": "YYYY (detect from document)",
        "filing_date": "YYYY-MM-DD if found"
    }
}

**EXTRACTION GUIDELINES:**

1. **Geographic Revenue:**
   - Look in Item 7 (MD&A) or Item 8 (Financial Statements) 
   - Find "Revenue by Geography" or "Segment Reporting"
   - Use EXACT names from tables (don't translate or standardize)
   - If percentages given, use those
   - If dollar amounts given, calculate percentages
   - If neither, return empty object

2. **Business Segments:**
   - Look for "Revenue by Product" or "Business Segments"
   - Use company's terminology (iPhone, Cloud Services, Therapeutics, etc.)
   - Extract AS REPORTED

3. **Numbers:**
   - Full USD amounts (5200000000 not "5.2B")
   - Use null if not found

4. **Fiscal Year:**
   - Detect from document (look for "fiscal year ended", filing date, etc.)
   - Common patterns: 2024, 2023, FY2024

5. **Flexibility:**
   - If a company doesn't report certain data, use null or empty
   - DO NOT invent structure
   - Adapt to what's actually there

**10-K CONTENT:**
{content}

**JSON OUTPUT (adapt structure to document):**"""

# ============================================================================
# EXTRACTION INTELLIGENTE
# ============================================================================

def extract_text_smart(html_path: Path) -> str:
    """Extrait le texte intelligemment"""
    try:
        with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
            html_content = f.read()
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Retirer éléments inutiles
        for element in soup(["script", "style", "meta", "link"]):
            element.decompose()
        
        text = soup.get_text(separator='\n', strip=True)
        
        # Extraction par sections si trop grand
        if len(text) > CHAR_LIMIT:
            sections = extract_key_sections(text)
            if sections:
                text = sections
        
        # Découpe intelligente en dernier recours
        if len(text) > CHAR_LIMIT:
            part1 = int(CHAR_LIMIT * 0.4)
            part2 = int(CHAR_LIMIT * 0.4)
            part3 = int(CHAR_LIMIT * 0.2)
            
            mid = len(text) // 2
            
            text = (
                text[:part1] + 
                "\n\n[...MIDDLE SECTION...]\n\n" +
                text[mid:mid+part2] +
                "\n\n[...]\n\n" +
                text[-part3:]
            )
        
        return text
    
    except Exception as e:
        log_error(html_path.name, f"Text extraction error: {e}")
        return ""


def extract_key_sections(text: str) -> str:
    """Extrait sections clés"""
    sections = []
    text_lower = text.lower()
    
    patterns = [
        (r'item\s*1[^a0-9].*?business', 30000),
        (r'item\s*1a.*?risk', 20000),
        (r'item\s*7[^a].*?management', 40000),
        (r'item\s*8.*?financial', 30000),
    ]
    
    for pattern, max_len in patterns:
        matches = list(re.finditer(pattern, text_lower, re.IGNORECASE))
        if matches:
            start = matches[0].start()
            section = text[start:start + max_len]
            sections.append(section)
    
    if sections:
        return "\n\n=== SECTION ===\n\n".join(sections)[:CHAR_LIMIT]
    
    return ""


# ============================================================================
# BEDROCK
# ============================================================================

def call_bedrock(prompt: str) -> Optional[Dict]:
    """Appelle Bedrock avec retry"""
    for retry in range(MAX_RETRIES):
        try:
            if retry > 0:
                time.sleep(min(2 ** retry, 10))
            
            response = BEDROCK_CLIENT.invoke_model(
                modelId=MODEL_ID,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "temperature": 0.0,
                    "messages": [{
                        "role": "user",
                        "content": [{"type": "text", "text": prompt}]
                    }]
                })
            )
            
            response_body = json.loads(response['body'].read())
            response_text = response_body['content'][0]['text']
            
            cleaned = clean_json_response(response_text)
            data = json.loads(cleaned)
            
            # Normaliser la structure pour compatibilité
            data = normalize_structure(data)
            
            return data
        
        except json.JSONDecodeError as e:
            if retry < MAX_RETRIES - 1:
                continue
            log_error("json", f"JSON error: {e}")
            return None
        
        except Exception as e:
            if 'throttl' in str(e).lower():
                time.sleep(5 * (retry + 1))
                if retry < MAX_RETRIES - 1:
                    continue
            
            if retry < MAX_RETRIES - 1:
                continue
            
            log_error("bedrock", f"Error: {e}")
            return None
    
    return None


def clean_json_response(text: str) -> str:
    """Nettoie JSON"""
    text = text.strip()
    
    if text.startswith('```json'):
        text = text[7:]
    elif text.startswith('```'):
        text = text[3:]
    
    if text.endswith('```'):
        text = text[:-3]
    
    return text.strip()


def normalize_structure(data: Dict) -> Dict:
    """
    Normalise la structure flexible pour compatibilité avec analyses
    Garde les données originales mais ajoute des champs standardisés
    """
    normalized = {
        'company_info': data.get('company_info', {}),
        'geographic_revenue': data.get('geographic_revenue', {}),
        'business_segments': data.get('business_segments', {}),
        'key_financials': data.get('key_financials', {}),
        'supply_chain': data.get('supply_chain', {}),
        'metadata': data.get('metadata', {}),
        
        # Champs legacy pour compatibilité (si besoin)
        'identity_and_jurisdiction': {
            'company_name': data.get('company_info', {}).get('name'),
            'trading_symbol': data.get('company_info', {}).get('ticker'),
            'legal_domicile_country': data.get('company_info', {}).get('domicile_country'),
            'sector_industry': data.get('company_info', {}).get('sector')
        },
        
        'geographic_exposure': {
            # Convertir la structure flexible en format legacy si nécessaire
            'regions': data.get('geographic_revenue', {}),
            'regions_of_activity': ', '.join(data.get('geographic_revenue', {}).keys())
        },
        
        'business_mix': {
            # Garder la structure flexible
            'segments': data.get('business_segments', {})
        },
        
        'supply_chain_and_commitments': {
            'suppliers_sector_industries': data.get('supply_chain', {}).get('major_suppliers_industries', []),
            'key_countries': data.get('supply_chain', {}).get('key_supplier_countries', []),
            'purchase_obligations_usd': data.get('key_financials', {}).get('purchase_obligations_usd')
        },
        
        'tax_and_innovation': {
            'r_and_d_expense_usd': data.get('key_financials', {}).get('r_and_d_expense_usd')
        }
    }
    
    return normalized


# ============================================================================
# TRAITEMENT
# ============================================================================

def process_single_10k(html_path: Path, progress: dict) -> Dict:
    """Traite un fichier"""
    ticker = html_path.parent.name
    
    try:
        text = extract_text_smart(html_path)
        if not text:
            progress['failed'] += 1
            return create_error_result(ticker, html_path, 'Empty extraction')
        
        prompt = EXTRACTION_PROMPT.format(content=text)
        data = call_bedrock(prompt)
        
        if data:
            progress['success'] += 1
            return {
                'ticker': ticker,
                'file_path': str(html_path),
                'success': True,
                'data': data,
                'extracted_at': datetime.now().isoformat()
            }
        else:
            progress['failed'] += 1
            return create_error_result(ticker, html_path, 'Bedrock failed')
    
    except Exception as e:
        progress['failed'] += 1
        log_error(ticker, str(e))
        return create_error_result(ticker, html_path, str(e))


def create_error_result(ticker: str, path: Path, error: str) -> Dict:
    """Résultat d'erreur"""
    return {
        'ticker': ticker,
        'file_path': str(path),
        'success': False,
        'error': error
    }


def log_error(ticker: str, msg: str):
    """Log erreurs"""
    ERROR_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now().isoformat()}] {ticker}: {msg}\n")


# ============================================================================
# FONCTION PRINCIPALE
# ============================================================================

def extract_all_10k(sample_size: Optional[int] = None, dry_run: bool = False):
    """Extraction générique"""
    
    print("\n" + "="*70)
    print("🚀 EXTRACTION 10-K GÉNÉRIQUE - DATATHON POLYFINANCES 2025")
    print("="*70 + "\n")
    
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    
    # Trouver fichiers
    all_files = []
    for ticker_dir in FILLINGS_DIR.iterdir():
        if ticker_dir.is_dir():
            html_files = list(ticker_dir.glob("*.html"))
            if html_files:
                all_files.append(html_files[0])
    
    print(f"📁 Fichiers trouvés: {len(all_files)}")
    
    if dry_run:
        print("🧪 MODE TEST - 5 fichiers")
        all_files = all_files[:5]
    elif sample_size:
        print(f"📊 ÉCHANTILLON - {sample_size} fichiers")
        all_files = all_files[:sample_size]
    else:
        print(f"🔥 MODE COMPLET - {len(all_files)} fichiers")
    
    print(f"⚙️  Workers: {MAX_WORKERS} | Retries: {MAX_RETRIES}")
    print("🎯 IA s'adapte automatiquement aux régions/segments")
    print()
    
    # Traitement
    results = []
    progress = {'success': 0, 'failed': 0}
    start = time.time()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_single_10k, f, progress): f 
            for f in all_files
        }
        
        with tqdm(total=len(all_files), desc="⏳ Extraction") as pbar:
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                
                pbar.set_postfix({
                    '✅': progress['success'],
                    '❌': progress['failed']
                })
                pbar.update(1)
                
                # Rate limiting adaptatif
                if progress['failed'] > progress['success'] * 0.3:
                    time.sleep(0.5)
                else:
                    time.sleep(0.1)
    
    elapsed = time.time() - start
    success = sum(1 for r in results if r['success'])
    failed = len(results) - success
    
    # Stats
    print("\n" + "="*70)
    print("📊 RÉSULTATS")
    print("="*70)
    print(f"✅ Succès:  {success}/{len(results)} ({success/len(results)*100:.1f}%)")
    print(f"❌ Échecs:  {failed}")
    print(f"⏱️  Durée:   {elapsed/60:.1f} min")
    print(f"⚡ Vitesse: {len(results)/elapsed*60:.1f} fichiers/min")
    
    # Sauvegarder
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n💾 Sauvegardé: {OUTPUT_FILE}")
    
    if failed > 0:
        print(f"⚠️  Erreurs: {ERROR_LOG_FILE}")
    
    # CSV
    df = pd.DataFrame([
        {
            'ticker': r['ticker'],
            'success': r['success'],
            'company': r.get('data', {}).get('company_info', {}).get('name') if r['success'] else None,
            'sector': r.get('data', {}).get('company_info', {}).get('sector') if r['success'] else None,
            'fiscal_year': r.get('data', {}).get('metadata', {}).get('fiscal_year') if r['success'] else None,
            'error': r.get('error') if not r['success'] else None
        }
        for r in results
    ])
    
    csv_file = OUTPUT_FILE.with_suffix('.csv')
    df.to_csv(csv_file, index=False)
    print(f"📄 CSV: {csv_file}")
    
    # Exemples de flexibilité
    if success > 0:
        print(f"\n📈 Extraction flexible:")
        print(f"   - Entreprises extraites: {success}")
        
        # Montrer diversité des régions
        all_regions = set()
        for r in results:
            if r['success']:
                regions = r.get('data', {}).get('geographic_revenue', {})
                all_regions.update(regions.keys())
        
        if all_regions:
            print(f"   - Régions détectées: {len(all_regions)}")
            print(f"     Exemples: {', '.join(list(all_regions)[:5])}")
    
    print("\n" + "="*70)
    print(" EXTRACTION TERMINÉE !")
    print("="*70 + "\n")
    
    return results


# ============================================================================
# POINT D'ENTRÉE
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Extraction 10-K générique (s'adapte aux données)"
    )
    parser.add_argument('--dry-run', action='store_true', help='Test 5 fichiers')
    parser.add_argument('--sample', type=int, help='N fichiers')
    parser.add_argument('--full', action='store_true', help='Tous les fichiers')
    
    args = parser.parse_args()
    
    if args.dry_run:
        extract_all_10k(dry_run=True)
    elif args.sample:
        extract_all_10k(sample_size=args.sample)
    elif args.full:
        extract_all_10k()
    else:
        print("\n OPTIONS:")
        print("   --dry-run : Test 5 fichiers")
        print("   --sample N : Traiter N fichiers")
        print("   --full : Tous les fichiers")
        print("\n Lancement dry-run...\n")
        extract_all_10k(dry_run=True)