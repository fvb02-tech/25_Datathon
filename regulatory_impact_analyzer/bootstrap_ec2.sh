#!/bin/bash
# ============================================================================
# BOOTSTRAP EC2 - RegShield Dashboard
# ============================================================================
# Ce script installe et configure tout sur l'EC2
# À exécuter UNE SEULE FOIS sur l'instance EC2
# ============================================================================

set -e  # Stop on error

echo "🚀 BOOTSTRAP REGSHIELD EC2"
echo "=========================================="
echo ""

# ============================================================================
# 1. UPDATE SYSTÈME
# ============================================================================

echo "📦 Mise à jour du système..."
sudo apt-get update -qq
sudo apt-get upgrade -y -qq

# ============================================================================
# 2. INSTALLER PYTHON ET DÉPENDANCES
# ============================================================================

echo "🐍 Installation Python 3.11 et pip..."
sudo apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-venv \
    unzip \
    wget \
    curl \
    htop

# ============================================================================
# 3. CRÉER STRUCTURE DE DOSSIERS
# ============================================================================

echo "📁 Création structure /opt/regshield..."
sudo mkdir -p /opt/regshield/{data,logs,dashboard,app}
sudo chown -R ubuntu:ubuntu /opt/regshield

# ============================================================================
# 4. INSTALLER DÉPENDANCES PYTHON
# ============================================================================

echo "📚 Installation dépendances Python..."
pip3 install --quiet --break-system-packages \
    dash==2.14.2 \
    dash-bootstrap-components==1.5.0 \
    plotly==5.18.0 \
    pandas==2.1.4 \
    gunicorn==21.2.0 \
    boto3

# ============================================================================
# 5. CRÉER SERVICE SYSTEMD
# ============================================================================

echo "⚙️  Configuration service systemd..."
sudo tee /etc/systemd/system/regshield.service > /dev/null <<'EOF'
[Unit]
Description=RegShield Dashboard - Datathon 2025
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/regshield/dashboard
Environment="PATH=/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/usr/local/bin/gunicorn -b 0.0.0.0:8050 --workers 2 --timeout 120 app:server
Restart=always
RestartSec=10
StandardOutput=append:/opt/regshield/logs/dashboard.log
StandardError=append:/opt/regshield/logs/dashboard.error.log

[Install]
WantedBy=multi-user.target
EOF

# Recharger systemd
sudo systemctl daemon-reload

# ============================================================================
# 6. CRÉER FICHIER DE CONFIG PLACEHOLDER
# ============================================================================

echo "📝 Création fichier config placeholder..."
cat > /opt/regshield/config.py <<'EOF'
from pathlib import Path
import os

# Chemins
PROJECT_DIR = Path("/opt/regshield")
PROCESSED_DIR = PROJECT_DIR / "data"
FILLINGS_DIR = PROJECT_DIR / "data"
DIRECTIVE_DIR = PROJECT_DIR / "data"

# AWS (non utilisé sur EC2, juste pour compatibilité)
AWS_REGION = "us-west-2"
MODEL_ID = "anthropic.claude-sonnet-4-20250514"
MODEL_ID_10K = "anthropic.claude-sonnet-4-20250514"
EOF

# ============================================================================
# 7. CRÉER README DANS /opt/regshield
# ============================================================================

cat > /opt/regshield/README.md <<'EOF'
# RegShield Dashboard - EC2 Instance

## Structure
```
/opt/regshield/
├── dashboard/        # Code dashboard Dash
├── app/              # Code analyse
├── data/             # Données JSON/CSV
└── logs/             # Logs du service
```

## Commandes utiles

### Service
```bash
sudo systemctl status regshield    # Status
sudo systemctl start regshield     # Démarrer
sudo systemctl stop regshield      # Arrêter
sudo systemctl restart regshield   # Redémarrer
```

### Logs
```bash
sudo journalctl -u regshield -f           # Logs temps réel
tail -f /opt/regshield/logs/dashboard.log # Logs application
```

### Update depuis SageMaker
Depuis SageMaker, exécutez :
```bash
./sync_from_sagemaker.sh
```
EOF

# ============================================================================
# 8. CRÉER SCRIPT DE STATUS LOCAL
# ============================================================================

cat > /opt/regshield/check.sh <<'EOF'
#!/bin/bash
echo "🔍 STATUS REGSHIELD DASHBOARD"
echo "======================================"
echo ""
echo "📊 Service Status:"
sudo systemctl status regshield --no-pager | head -20
echo ""
echo "📝 Dernières lignes de log:"
sudo journalctl -u regshield -n 10 --no-pager
echo ""
echo "🌐 Test local:"
curl -s http://localhost:8050 | head -5 || echo "❌ Dashboard non accessible"
echo ""
echo "💾 Fichiers de données:"
ls -lh /opt/regshield/data/*.json /opt/regshield/data/*.csv 2>/dev/null || echo "⚠️  Pas encore de données"
EOF

chmod +x /opt/regshield/check.sh

# ============================================================================
# 9. AFFICHER INFO FINALE
# ============================================================================

echo ""
echo "=========================================="
echo "✅ BOOTSTRAP TERMINÉ !"
echo "=========================================="
echo ""
echo "📋 Prochaines étapes :"
echo ""
echo "1. Depuis SageMaker, syncronisez les données :"
echo "   ./sync_from_sagemaker.sh"
echo ""
echo "2. Démarrez le dashboard :"
echo "   sudo systemctl start regshield"
echo ""
echo "3. Vérifiez le status :"
echo "   /opt/regshield/check.sh"
echo ""
echo "4. Accédez au dashboard :"
echo "   http://[VOTRE-IP-PUBLIQUE]:8050"
echo ""
echo "📁 Structure créée dans : /opt/regshield"
echo "📝 Logs dans : /opt/regshield/logs/"
echo ""
echo "🎯 Service systemd configuré : regshield.service"
echo ""

# Afficher IP publique
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
if [ -n "$PUBLIC_IP" ]; then
    echo "🌐 Votre URL sera : http://$PUBLIC_IP:8050"
else
    echo "⚠️  Récupérez l'IP publique depuis la console EC2"
fi

echo ""
echo "✅ Prêt pour la synchronisation !"
echo ""
