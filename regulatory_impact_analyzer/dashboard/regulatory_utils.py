"""
Utilitaires pour le parsing et le chargement de données
Datathon PolyFinances 2025
"""

import json
import base64
import io
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

from config import (
    COMPANY_DATA_FILENAMES,
    COMPANY_DATA_SEARCH_PATHS,
    PRECALCULATED_SCORES,
    REGULATORY_KEYWORDS,
    MIN_DOCUMENT_LENGTH,
    MIN_KEYWORD_MATCHES,
    HTML_IGNORE_TAGS,
    XML_CONTENT_TAGS
)


# ============================================================================
# PARSERS DE DOCUMENTS
# ============================================================================

class HTMLTextExtractor(HTMLParser):
    """Extracteur de texte depuis HTML en ignorant les balises non-pertinentes"""
    
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.ignore_content = False
        self.ignore_tags = HTML_IGNORE_TAGS
    
    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.ignore_tags:
            self.ignore_content = True
    
    def handle_endtag(self, tag):
        if tag.lower() in self.ignore_tags:
            self.ignore_content = False
    
    def handle_data(self, data):
        if not self.ignore_content:
            text = data.strip()
            if text:
                self.text_parts.append(text)
    
    def get_text(self):
        return ' '.join(self.text_parts)


def parse_xml_document(xml_content: str) -> str:
    """Parse un document XML et extrait le texte des balises pertinentes"""
    try:
        root = ET.fromstring(xml_content)
        text_parts = []
        
        for elem in root.iter():
            tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            
            if tag_name.lower() in [t.lower() for t in XML_CONTENT_TAGS]:
                if elem.text and elem.text.strip():
                    text_parts.append(elem.text.strip())
            
            if elem.tail and elem.tail.strip():
                text_parts.append(elem.tail.strip())
        
        return ' '.join(text_parts)
    
    except ET.ParseError:
        return xml_content


def parse_html_document(html_content: str) -> str:
    """Parse un document HTML et extrait le texte en ignorant navigation/scripts"""
    try:
        parser = HTMLTextExtractor()
        parser.feed(html_content)
        extracted_text = parser.get_text()
        
        # Si l'extraction structurée donne peu de résultats, fallback sur regex
        if len(extracted_text) < 200:
            # Supprimer scripts, styles, nav
            text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<header[^>]*>.*?</header>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.DOTALL | re.IGNORECASE)
            # Supprimer toutes les balises HTML
            text = re.sub(r'<[^>]+>', ' ', text)
            # Nettoyer les espaces multiples
            text = ' '.join(text.split())
            extracted_text = text
        
        return extracted_text
    except Exception:
        # Fallback complet sur regex
        text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        return ' '.join(text.split())


def parse_pdf_document(pdf_bytes: bytes) -> str:
    """Parse un document PDF et extrait le texte"""
    if not PDF_AVAILABLE:
        return ""
    
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text_parts = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            return '\n'.join(text_parts)
    except Exception:
        return ""


def parse_any_format(contents: str, filename: str) -> str:
    """
    Parse un document de n'importe quel format supporté (TXT, PDF, XML, HTML)
    
    Args:
        contents: Contenu encodé en base64
        filename: Nom du fichier
    
    Returns:
        Texte extrait du document
    """
    try:
        content_string = contents.split(',')[1]
        decoded = base64.b64decode(content_string)
        
        ext = filename.lower().split('.')[-1]
        
        if ext == 'pdf':
            return parse_pdf_document(decoded)
        
        try:
            text = decoded.decode('utf-8')
        except UnicodeDecodeError:
            text = decoded.decode('latin-1', errors='ignore')
        
        if ext == 'xml':
            return parse_xml_document(text)
        
        if ext in ['html', 'htm']:
            return parse_html_document(text)
        
        return text
    
    except Exception:
        return ""


def validate_regulatory_document(text: str) -> Tuple[bool, str]:
    """
    Valide qu'un document est bien un document réglementaire
    
    Args:
        text: Texte du document
    
    Returns:
        (is_valid, message)
    """
    if not text or len(text) < MIN_DOCUMENT_LENGTH:
        return False, f"Document trop court (minimum {MIN_DOCUMENT_LENGTH} caractères)"
    
    text_lower = text.lower()
    matches = sum(1 for keyword in REGULATORY_KEYWORDS if keyword in text_lower)
    
    if matches < MIN_KEYWORD_MATCHES:
        return False, f"Document ne contient pas assez de mots-clés réglementaires (trouvé {matches}, minimum {MIN_KEYWORD_MATCHES})"
    
    return True, "Document validé"


# ============================================================================
# CHARGEURS DE DONNÉES
# ============================================================================

def find_company_data_file() -> Optional[Path]:
    """
    Recherche le fichier company_10k_data avec support des variantes (_1_, _2_, etc.)
    
    Returns:
        Path du fichier trouvé ou None
    """
    for search_path in COMPANY_DATA_SEARCH_PATHS:
        search_path = search_path.resolve()
        
        for filename in COMPANY_DATA_FILENAMES:
            file_path = search_path / filename
            if file_path.exists():
                return file_path
        
        pattern_matches = list(search_path.glob("company_10k_data*.json"))
        if pattern_matches:
            return pattern_matches[0]
    
    return None


def load_company_data() -> List[Dict]:
    """
    Charge les données des entreprises depuis company_10k_data*.json
    
    Returns:
        Liste de dictionnaires avec format {'ticker': str, 'data': dict, 'success': bool}
    """
    file_path = find_company_data_file()
    
    if not file_path:
        return []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        companies = []
        
        if isinstance(data, dict):
            for ticker, company_data in data.items():
                if isinstance(company_data, dict):
                    company_entry = {
                        'ticker': ticker,
                        'data': company_data,
                        'success': True
                    }
                    companies.append(company_entry)
        
        elif isinstance(data, list):
            if len(data) > 0 and isinstance(data[0], dict):
                companies = [d for d in data if isinstance(d, dict) and d.get('success', True)]
        
        return companies
        
    except Exception:
        return []


def find_precalculated_law_file(law_name: str) -> Optional[Path]:
    """
    Recherche un fichier de scores pré-calculés (Law1, Law2, etc.)
    
    Args:
        law_name: Nom de la loi ("Law1", "Law2", etc.)
    
    Returns:
        Path du fichier trouvé ou None
    """
    if law_name not in PRECALCULATED_SCORES:
        return None
    
    for file_path in PRECALCULATED_SCORES[law_name]:
        file_path = file_path.resolve()
        if file_path.exists():
            return file_path
    
    return None


def load_precalculated_scores(law_name: str) -> Optional[List[Dict]]:
    """
    Charge les scores pré-calculés pour une loi donnée
    
    Args:
        law_name: Nom de la loi ("Law1", "Law2", etc.)
    
    Returns:
        Liste de dictionnaires avec les scores ou None si non trouvé
    """
    file_path = find_precalculated_law_file(law_name)
    
    if not file_path:
        return None
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception:
        return None


# ============================================================================
# FORMATTAGE DONNÉES ENTREPRISE
# ============================================================================

def format_company_profile(company_data: Dict) -> Dict[str, str]:
    """
    Formate les informations d'une entreprise pour analyse
    
    Args:
        company_data: Données brutes de l'entreprise
    
    Returns:
        Dictionnaire avec informations formatées
    """
    ticker = company_data.get('ticker', 'UNK')
    data = company_data.get('data', {})
    
    identity = data.get('identity_and_jurisdiction', {})
    company_name = identity.get('company_name', 'Unknown')
    sector = identity.get('sector_industry', 'Unknown')
    
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
    
    biz = data.get('business_mix', {})
    business_parts = []
    if biz.get('products_revenue_usd'):
        business_parts.append(f"Products: ${biz['products_revenue_usd']/1e9:.1f}B")
    if biz.get('services_revenue_usd'):
        business_parts.append(f"Services: ${biz['services_revenue_usd']/1e9:.1f}B")
    business_mix = ", ".join(business_parts) if business_parts else "Not disclosed"
    
    supply = data.get('supply_chain_and_commitments', {})
    suppliers = supply.get('suppliers_sector_industries', [])
    supply_chain = ", ".join(suppliers[:3]) if suppliers else "Not disclosed"
    
    tax_innov = data.get('tax_and_innovation', {})
    r_and_d_value = tax_innov.get('r_and_d_expense_usd')
    r_and_d = f"${r_and_d_value/1e9:.1f}B" if r_and_d_value else "Not disclosed"
    
    return {
        'ticker': ticker,
        'company_name': company_name,
        'sector': sector,
        'geography': geography,
        'business_mix': business_mix,
        'supply_chain': supply_chain,
        'r_and_d': r_and_d
    }