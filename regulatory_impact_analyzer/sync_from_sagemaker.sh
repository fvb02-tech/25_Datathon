#!/bin/bash
# ============================================================================
# SYNC SAGEMAKER → EC2 - RegShield
# ============================================================================
# Synchronise code et données depuis SageMaker vers EC2
# À exécuter DEPUIS SAGEMAKER
# ============================================================================

set -e

# ============================================================================
# CONFIGURATION - MODIFIEZ CES VALEURS
# ============================================================================

# ⚠️ REMPLACEZ PAR L'IP PRIVÉE DE VOTRE EC2
EC2_PRIVATE_IP="10.38.230.6"  # <-- CHANGEZ ICI !

# Chemins
SAGEMAKER_BASE="/mnt/custom-file-systems/s3/shared/regulatory_impact_analyzer"
SSH_KEY="$SAGEMAKER_BASE/datathon.pem"
EC2_USER="ubuntu"
EC2_BASE="/opt/regshield"

# ============================================================================
# VÉRIFICATIONS PRÉALABLES
# ============================================================================

echo "🔍 SYNC REGSHIELD : SageMaker → EC2"
echo "=========================================="
echo ""

# Vérifier que la clé SSH existe
if [ ! -f "$SSH_KEY" ]; then
    echo "❌ Erreur : Clé SSH introuvable à $SSH_KEY"
    exit 1
fi

# Vérifier les permissions de la clé
chmod 400 "$SSH_KEY"

# Test connexion SSH
echo "🔌 Test connexion SSH vers EC2..."
if ! ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_PRIVATE_IP" "echo 'OK'" &>/dev/null; then
    echo "❌ Erreur : Impossible de se connecter à $EC2_PRIVATE_IP"
    echo ""
    echo "Vérifiez :"
    echo "  1. L'IP privée EC2 est correcte : $EC2_PRIVATE_IP"
    echo "  2. Le Security Group autorise SSH depuis SageMaker"
    echo "  3. L'instance EC2 est démarrée"
    exit 1
fi

echo "✅ Connexion SSH OK"
echo ""

# ============================================================================
# SYNCHRONISATION DES DONNÉES
# ============================================================================

echo "📊 Sync données (data/processed/)..."
rsync -avz --progress \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    "$SAGEMAKER_BASE/data/processed/" \
    "$EC2_USER@$EC2_PRIVATE_IP:$EC2_BASE/data/" \
    --exclude='*.log' \
    --exclude='__pycache__'

echo ""
echo "✅ Données synchronisées"
echo ""

# ============================================================================
# SYNCHRONISATION DU CODE DASHBOARD
# ============================================================================

echo "🎨 Sync dashboard..."
rsync -avz --progress \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    "$SAGEMAKER_BASE/dashboard/" \
    "$EC2_USER@$EC2_PRIVATE_IP:$EC2_BASE/dashboard/" \
    --exclude='__pycache__' \
    --exclude='*.pyc'

echo ""
echo "✅ Dashboard synchronisé"
echo ""

# ============================================================================
# SYNCHRONISATION DU CODE APP
# ============================================================================

echo "⚙️  Sync app..."
rsync -avz --progress \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    "$SAGEMAKER_BASE/app/" \
    "$EC2_USER@$EC2_PRIVATE_IP:$EC2_BASE/app/" \
    --exclude='__pycache__' \
    --exclude='*.pyc'

echo ""
echo "✅ App synchronisée"
echo ""

# ============================================================================
# SYNCHRONISATION CONFIG
# ============================================================================

echo "📝 Sync config.py..."
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    "$SAGEMAKER_BASE/config.py" \
    "$EC2_USER@$EC2_PRIVATE_IP:$EC2_BASE/config.py"

echo ""
echo "✅ Config synchronisée"
echo ""

# ============================================================================
# REDÉMARRAGE DU SERVICE
# ============================================================================

echo "🔄 Redémarrage du dashboard..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    "$EC2_USER@$EC2_PRIVATE_IP" \
    "sudo systemctl restart regshield && sleep 2 && sudo systemctl status regshield --no-pager | head -10"

echo ""

# ============================================================================
# VÉRIFICATION FINALE
# ============================================================================

echo "=========================================="
echo "✅ SYNCHRONISATION TERMINÉE !"
echo "=========================================="
echo ""

# Récupérer IP publique de l'EC2
PUBLIC_IP=$(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    "$EC2_USER@$EC2_PRIVATE_IP" \
    "curl -s http://169.254.169.254/latest/meta-data/public-ipv4")

if [ -n "$PUBLIC_IP" ]; then
    echo "🌐 Dashboard accessible à :"
    echo ""
    echo "   http://$PUBLIC_IP:8050"
    echo ""
else
    echo "⚠️  Récupérez l'IP publique depuis la console EC2"
fi

echo "📊 Fichiers synchronisés :"
echo "  - Données : data/processed/*.{json,csv}"
echo "  - Dashboard : dashboard/app.py"
echo "  - App : app/*.py"
echo "  - Config : config.py"
echo ""

echo "💡 Commandes utiles :"
echo ""
echo "  Vérifier status :"
echo "    ./check_status.sh"
echo ""
echo "  Update code seulement (plus rapide) :"
echo "    ./update_code.sh"
echo ""
echo "  Voir logs en temps réel :"
echo "    ssh -i $SSH_KEY $EC2_USER@$EC2_PRIVATE_IP 'sudo journalctl -u regshield -f'"
echo ""

echo "✅ Votre dashboard est prêt !"
echo ""
