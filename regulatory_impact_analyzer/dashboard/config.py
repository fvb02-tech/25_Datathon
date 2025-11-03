"""
Configuration centralisée pour PolicyPulse
Datathon PolyFinances 2025
"""

from pathlib import Path

# ============================================================================
# CHEMINS DE DONNÉES
# ============================================================================

# Données des entreprises (10-K)
COMPANY_DATA_FILENAMES = [
    "company_10k_data.json",
    "company_10k_data_1_.json",
    "company_10k_data_2_.json",
]

COMPANY_DATA_SEARCH_PATHS = [
    Path("/opt/regshield/data"),
    Path("/mnt/custom-file-systems/s3/shared/regulatory_impact_analyzer/data/processed"),
    Path(__file__).parent / "data" / "processed",
    Path(__file__).parent / "data",
    Path(__file__).parent / "shared",
    Path(__file__).parent,
]

# Scores pré-calculés (Law1, Law2)
PRECALCULATED_SCORES = {
    "Law1": [
        Path("/opt/regshield/shared/Law1_Risk_score_500_ok.json"),
        Path("/mnt/custom-file-systems/s3/shared/Law1_Risk_score_500_ok.json"),
        Path(__file__).parent / "shared" / "Law1_Risk_score_500_ok.json",
        Path(__file__).parent / "Law1_Risk_score_500_ok.json",
    ],
    "Law2": [
        Path("/opt/regshield/shared/Law2_Risk_score_500_ok_old.json"),
        Path("/mnt/custom-file-systems/s3/shared/Law2_Risk_score_500_ok_old.json"),
        Path(__file__).parent / "shared" / "Law2_Risk_score_500_ok_old.json",
        Path(__file__).parent / "Law2_Risk_score_500_ok_old.json",
    ],
}

# ============================================================================
# CONFIGURATION BEDROCK
# ============================================================================

BEDROCK_CONFIG = {
    "model_id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "region": "us-west-2",
    "max_tokens": 1500,
    "temperature": 0.3,
}

# ============================================================================
# CONFIGURATION ANALYSE
# ============================================================================

# Parallélisation
MAX_WORKERS = 50

# Validation documents réglementaires
REGULATORY_KEYWORDS = [
    # Anglais
    'regulation', 'law', 'policy', 'compliance', 'directive', 'decree',
    'act', 'statute', 'ordinance', 'legislation', 'amendment', 'requirement',
    'provision', 'enactment', 'bill',
    # Français
    'règlement', 'loi', 'politique', 'conformité', 'décret', 'ordonnance',
    # Chinois
    '法', '法律', '法规', '规定', '条例', '政策', '能源法',
    '中华人民共和国', '规章', '办法', '实施', '管理',
    # Espagnol
    'ley', 'reglamento', 'decreto',
    # Allemand
    'gesetz', 'verordnung',
]

MIN_DOCUMENT_LENGTH = 50  # Réduit de 100 à 50
MIN_KEYWORD_MATCHES = 1   # Réduit de 2 à 1 (1 seul mot-clé suffit)

# ============================================================================
# CONFIGURATION PARSERS
# ============================================================================

# Tags HTML à ignorer lors du parsing
HTML_IGNORE_TAGS = ['script', 'style', 'nav', 'header', 'footer', 'aside']

# Tags XML pertinents pour extraction de contenu
XML_CONTENT_TAGS = [
    'section', 'content', 'heading', 'title', 'text', 'paragraph',
    'article', 'chapter', 'part', 'subsection'
]