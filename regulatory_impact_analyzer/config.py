from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

# Chemins
FILLINGS_DIR = Path(os.getenv('FILLINGS_DIR'))
DIRECTIVE_DIR = Path(os.getenv('DIRECTIVE_DIR'))
PROJECT_DIR = Path(os.getenv('PROJECT_DIR'))
PROCESSED_DIR = Path(os.getenv('PROCESSED_DIR'))



# AWS
AWS_REGION = os.getenv('AWS_REGION', 'us-west-2')
MODEL_ID = os.getenv('BEDROCK_MODEL_ID')
MODEL_ID_10K= os.getenv('K_MODEL')

