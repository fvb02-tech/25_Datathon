#!/bin/bash
# ============================================================================
# CONFIGURATION - Définir l'IP de l'EC2
# ============================================================================
# Ce script met à jour l'IP privée EC2 dans tous les scripts
# ============================================================================

echo " CONFIGURATION REGSHIELD"
echo "=========================================="
echo ""

# ============================================================================
# IP PRIVÉE
# ============================================================================

EC2_IP=10.38.230.6
echo ""
echo "IP validée : $EC2_IP"
echo ""

# ============================================================================
# METTRE À JOUR LES SCRIPTS
# ============================================================================

echo "Mise à jour des scripts..."

# Liste des scripts à modifier
SCRIPTS=(
    "sync_from_sagemaker.sh"
    "check_status.sh"
    "update_code.sh"
)

for script in "${SCRIPTS[@]}"; do
    if [ -f "$script" ]; then
        # Remplacer l'IP dans le script
        sed -i "s/EC2_PRIVATE_IP=\".*\"/EC2_PRIVATE_IP=\"$EC2_IP\"/" "$script"
        echo "  $script"
    else
        echo "   $script introuvable (skip)"
    fi
done

echo ""

# ============================================================================
# RENDRE EXÉCUTABLES
# ============================================================================

echo " Configuration des permissions..."
chmod +x sync_from_sagemaker.sh 2>/dev/null || true
chmod +x check_status.sh 2>/dev/null || true
chmod +x update_code.sh 2>/dev/null || true
chmod +x bootstrap_ec2.sh 2>/dev/null || true

echo "   Scripts exécutables"
echo ""

# ============================================================================
# TEST CONNEXION SSH
# ============================================================================

echo "🔌 Test connexion SSH..."
SSH_KEY="datathon.pem"

if [ ! -f "$SSH_KEY" ]; then
    echo "⚠️  Clé SSH 'datathon.pem' introuvable dans ce dossier"
    echo "   Assurez-vous d'être dans le bon répertoire"
    echo ""
else
    chmod 400 "$SSH_KEY"
    
    if ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
        "ubuntu@$EC2_IP" "echo 'OK'" &>/dev/null; then
        echo "✅ Connexion SSH fonctionne !"
    else
        echo "⚠️  Connexion SSH échouée"
        echo ""
        echo "Vérifiez :"
        echo "  1. L'instance EC2 est démarrée"
        echo "  2. Le Security Group autorise SSH depuis SageMaker"
        echo "  3. Vous êtes dans le bon répertoire"
    fi
fi

echo ""

# ============================================================================
# RÉSUMÉ
# ============================================================================

echo "=========================================="
echo "✅ CONFIGURATION TERMINÉE !"
echo "=========================================="
echo ""
echo "📋 IP EC2 configurée : $EC2_IP"
echo ""
echo "🚀 Prochaines étapes :"
echo ""
echo "1. Copiez bootstrap_ec2.sh sur l'EC2 :"
echo "   scp -i datathon.pem bootstrap_ec2.sh ubuntu@$EC2_IP:~/"
echo ""
echo "2. Connectez-vous en SSH et exécutez bootstrap :"
echo "   ssh -i datathon.pem ubuntu@$EC2_IP"
echo "   chmod +x bootstrap_ec2.sh"
echo "   ./bootstrap_ec2.sh"
echo ""
echo "3. Revenez dans SageMaker et synchronisez :"
echo "   ./sync_from_sagemaker.sh"
echo ""
echo "4. Vérifiez le status :"
echo "   ./check_status.sh"
echo ""
echo "💡 Voir le README.md pour plus de détails"
echo ""