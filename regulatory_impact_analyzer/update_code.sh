#!/bin/bash
# ============================================================================
# UPDATE CODE - RegShield Dashboard
# ============================================================================
# Synchronise SEULEMENT le code (pas les données)
# Plus rapide que sync_from_sagemaker.sh
# À exécuter DEPUIS SAGEMAKER
# ============================================================================

set -e

# ============================================================================
# CONFIGURATION - MODIFIEZ CETTE VALEUR
# ============================================================================

# ⚠️ REMPLACEZ PAR L'IP PRIVÉE DE VOTRE EC2
EC2_PRIVATE_IP="10.38.230.6"  # <-- CHANGEZ ICI !

# Chemins
SAGEMAKER_BASE="/mnt/custom-file-systems/s3/shared/regulatory_impact_analyzer"
SSH_KEY="$SAGEMAKER_BASE/datathon.pem"
EC2_USER="ubuntu"
EC2_BASE="/opt/regshield"

# ============================================================================
# VÉRIFICATIONS
# ============================================================================

echo "⚡ UPDATE CODE RAPIDE"
echo "=========================================="
echo ""

if [ ! -f "$SSH_KEY" ]; then
    echo "❌ Erreur : Clé SSH introuvable"
    exit 1
fi

chmod 400 "$SSH_KEY"

echo "🔌 Test connexion..."
if ! ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
    "$EC2_USER@$EC2_PRIVATE_IP" "echo 'OK'" &>/dev/null; then
    echo "❌ Connexion SSH impossible"
    exit 1
fi

echo "✅ Connexion OK"
echo ""

# ============================================================================
# UPDATE DASHBOARD
# ============================================================================

echo "🎨 Update dashboard/app.py..."
rsync -avz --progress \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    "$SAGEMAKER_BASE/dashboard/app.py" \
    "$EC2_USER@$EC2_PRIVATE_IP:$EC2_BASE/dashboard/app.py"

echo ""

# ============================================================================
# UPDATE APP (si besoin)
# ============================================================================

if [ -d "$SAGEMAKER_BASE/app" ]; then
    echo "⚙️  Update app/*.py..."
    rsync -avz --progress \
        -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
        "$SAGEMAKER_BASE/app/*.py" \
        "$EC2_USER@$EC2_PRIVATE_IP:$EC2_BASE/app/" 2>/dev/null || true
    echo ""
fi

# ============================================================================
# UPDATE CONFIG (si modifié)
# ============================================================================

echo "📝 Update config.py..."
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    "$SAGEMAKER_BASE/config.py" \
    "$EC2_USER@$EC2_PRIVATE_IP:$EC2_BASE/config.py" 2>/dev/null || true

echo ""

# ============================================================================
# REDÉMARRAGE
# ============================================================================

echo "🔄 Redémarrage du dashboard..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    "$EC2_USER@$EC2_PRIVATE_IP" \
    "sudo systemctl restart regshield"

echo ""
echo "⏳ Attente 3 secondes..."
sleep 3

# ============================================================================
# VÉRIFICATION
# ============================================================================

echo "🔍 Vérification status..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    "$EC2_USER@$EC2_PRIVATE_IP" \
    "sudo systemctl status regshield --no-pager | head -10"

echo ""

# ============================================================================
# RÉCUPÉRER IP PUBLIQUE
# ============================================================================

PUBLIC_IP=$(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    "$EC2_USER@$EC2_PRIVATE_IP" \
    "curl -s http://169.254.169.254/latest/meta-data/public-ipv4")

echo "=========================================="
echo "✅ CODE MIS À JOUR !"
echo "=========================================="
echo ""

if [ -n "$PUBLIC_IP" ]; then
    echo "🌐 Dashboard : http://$PUBLIC_IP:8050"
else
    echo "⚠️  Récupérez l'IP publique depuis la console"
fi

echo ""
echo "💡 Pour voir les logs en temps réel :"
echo "   ssh -i $SSH_KEY $EC2_USER@$EC2_PRIVATE_IP 'sudo journalctl -u regshield -f'"
echo ""
