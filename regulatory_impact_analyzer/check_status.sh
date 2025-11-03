#!/bin/bash
# ============================================================================
# CHECK STATUS - RegShield Dashboard
# ============================================================================
# Vérifie l'état du dashboard sur EC2
# À exécuter DEPUIS SAGEMAKER
# ============================================================================

# ============================================================================
# CONFIGURATION - MODIFIEZ CETTE VALEUR
# ============================================================================

# ⚠️ REMPLACEZ PAR L'IP PRIVÉE DE VOTRE EC2
EC2_PRIVATE_IP="10.38.230.6"  # <-- CHANGEZ ICI !

# Chemins
SAGEMAKER_BASE="/mnt/custom-file-systems/s3/shared/regulatory_impact_analyzer"
SSH_KEY="$SAGEMAKER_BASE/datathon.pem"
EC2_USER="ubuntu"

# ============================================================================
# VÉRIFICATIONS
# ============================================================================

echo "🔍 STATUS REGSHIELD DASHBOARD"
echo "=========================================="
echo ""

# Vérifier clé SSH
if [ ! -f "$SSH_KEY" ]; then
    echo "❌ Erreur : Clé SSH introuvable"
    exit 1
fi
chmod 400 "$SSH_KEY"

# ============================================================================
# 1. TEST CONNEXION SSH
# ============================================================================

echo "🔌 Test connexion SSH..."
if ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
    "$EC2_USER@$EC2_PRIVATE_IP" "echo '✅ SSH OK'" 2>/dev/null; then
    echo ""
else
    echo "❌ Connexion SSH impossible"
    echo ""
    echo "Vérifiez :"
    echo "  1. L'IP privée : $EC2_PRIVATE_IP"
    echo "  2. Le Security Group"
    echo "  3. L'instance EC2 est démarrée"
    exit 1
fi

# ============================================================================
# 2. STATUS SERVICE SYSTEMD
# ============================================================================

echo "📊 Status service systemd..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    "$EC2_USER@$EC2_PRIVATE_IP" \
    "sudo systemctl status regshield --no-pager | head -15"

echo ""

# ============================================================================
# 3. DERNIERS LOGS
# ============================================================================

echo "📝 Derniers logs (10 lignes)..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    "$EC2_USER@$EC2_PRIVATE_IP" \
    "sudo journalctl -u regshield -n 10 --no-pager"

echo ""

# ============================================================================
# 4. TEST HTTP LOCAL
# ============================================================================

echo "🌐 Test HTTP local (port 8050)..."
HTTP_TEST=$(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    "$EC2_USER@$EC2_PRIVATE_IP" \
    "curl -s -o /dev/null -w '%{http_code}' http://localhost:8050" 2>/dev/null)

if [ "$HTTP_TEST" = "200" ]; then
    echo "✅ Dashboard répond (HTTP 200)"
else
    echo "⚠️  Dashboard ne répond pas (HTTP $HTTP_TEST)"
fi

echo ""

# ============================================================================
# 5. FICHIERS DE DONNÉES
# ============================================================================

echo "💾 Fichiers de données présents..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    "$EC2_USER@$EC2_PRIVATE_IP" \
    "ls -lh /opt/regshield/data/*.json /opt/regshield/data/*.csv 2>/dev/null | tail -10" || \
    echo "⚠️  Aucune donnée trouvée - Exécutez ./sync_from_sagemaker.sh"

echo ""

# ============================================================================
# 6. RÉCUPÉRER IP PUBLIQUE
# ============================================================================

echo "🌐 URL publique du dashboard..."
PUBLIC_IP=$(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no \
    "$EC2_USER@$EC2_PRIVATE_IP" \
    "curl -s http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null)

if [ -n "$PUBLIC_IP" ]; then
    echo ""
    echo "=========================================="
    echo "🎯 ACCÉDEZ AU DASHBOARD :"
    echo ""
    echo "   http://$PUBLIC_IP:8050"
    echo ""
    echo "=========================================="
else
    echo "⚠️  IP publique non disponible"
fi

echo ""

# ============================================================================
# 7. COMMANDES UTILES
# ============================================================================

echo "💡 Commandes utiles :"
echo ""
echo "  Redémarrer le dashboard :"
echo "    ssh -i $SSH_KEY $EC2_USER@$EC2_PRIVATE_IP 'sudo systemctl restart regshield'"
echo ""
echo "  Voir logs en temps réel :"
echo "    ssh -i $SSH_KEY $EC2_USER@$EC2_PRIVATE_IP 'sudo journalctl -u regshield -f'"
echo ""
echo "  Connecter en SSH :"
echo "    ssh -i $SSH_KEY $EC2_USER@$EC2_PRIVATE_IP"
echo ""
