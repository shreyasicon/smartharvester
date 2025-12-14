#!/bin/bash
# Script to update COGNITO_DOMAIN in systemd environment file
# Usage: sudo bash scripts/fix_cognito_domain.sh

ENV_FILE="/etc/systemd/system/smartharvester.service.d/env.conf"
OLD_DOMAIN="myuserpool-ui.auth.us-east-1.amazoncognito.com"
NEW_DOMAIN="smartcrop-rocky-app.auth.us-east-1.amazoncognito.com"

echo "=========================================="
echo "Fixing Cognito Domain Configuration"
echo "=========================================="
echo ""

# Check if file exists
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: Environment file not found at $ENV_FILE"
    echo "Creating directory and file..."
    sudo mkdir -p /etc/systemd/system/smartharvester.service.d
    echo "COGNITO_DOMAIN=$NEW_DOMAIN" | sudo tee "$ENV_FILE" > /dev/null
    echo "✅ Created new environment file"
else
    echo "✅ Found environment file: $ENV_FILE"
    
    # Backup the file
    BACKUP_FILE="${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    sudo cp "$ENV_FILE" "$BACKUP_FILE"
    echo "✅ Created backup: $BACKUP_FILE"
    
    # Check current value
    CURRENT=$(sudo grep "^COGNITO_DOMAIN=" "$ENV_FILE" | cut -d'=' -f2)
    echo "Current COGNITO_DOMAIN: $CURRENT"
    
    # Update the domain
    if sudo grep -q "^COGNITO_DOMAIN=$OLD_DOMAIN" "$ENV_FILE"; then
        sudo sed -i "s|^COGNITO_DOMAIN=$OLD_DOMAIN|COGNITO_DOMAIN=$NEW_DOMAIN|" "$ENV_FILE"
        echo "✅ Updated COGNITO_DOMAIN from $OLD_DOMAIN to $NEW_DOMAIN"
    elif sudo grep -q "^COGNITO_DOMAIN=" "$ENV_FILE"; then
        # Domain exists but is different - update it anyway
        sudo sed -i "s|^COGNITO_DOMAIN=.*|COGNITO_DOMAIN=$NEW_DOMAIN|" "$ENV_FILE"
        echo "✅ Updated COGNITO_DOMAIN to $NEW_DOMAIN"
    else
        # Domain doesn't exist - add it
        echo "COGNITO_DOMAIN=$NEW_DOMAIN" | sudo tee -a "$ENV_FILE" > /dev/null
        echo "✅ Added COGNITO_DOMAIN=$NEW_DOMAIN"
    fi
    
    # Verify the change
    UPDATED=$(sudo grep "^COGNITO_DOMAIN=" "$ENV_FILE" | cut -d'=' -f2)
    echo "Updated COGNITO_DOMAIN: $UPDATED"
    
    if [ "$UPDATED" = "$NEW_DOMAIN" ]; then
        echo "✅ Domain updated successfully!"
    else
        echo "❌ Error: Domain update failed. Please check manually."
        exit 1
    fi
fi

echo ""
echo "=========================================="
echo "Reloading systemd and restarting service"
echo "=========================================="

# Reload systemd
sudo systemctl daemon-reload
echo "✅ Reloaded systemd configuration"

# Restart service
sudo systemctl restart smartharvester
echo "✅ Restarted smartharvester service"

# Verify the environment variable is loaded
echo ""
echo "=========================================="
echo "Verification"
echo "=========================================="
LOADED_DOMAIN=$(sudo systemctl show smartharvester --property=Environment | grep -oP 'COGNITO_DOMAIN=\K[^\s]+' || echo "NOT FOUND")
echo "COGNITO_DOMAIN in service environment: $LOADED_DOMAIN"

if [ "$LOADED_DOMAIN" = "$NEW_DOMAIN" ]; then
    echo "✅ SUCCESS: Domain is correctly loaded!"
    echo ""
    echo "Next steps:"
    echo "1. Check service logs: sudo journalctl -u smartharvester -f"
    echo "2. Test login: https://3.235.196.246.nip.io/auth/login/"
else
    echo "⚠️  WARNING: Domain may not be loaded correctly"
    echo "Please verify:"
    echo "1. Service unit includes EnvironmentFile directive"
    echo "2. File permissions are correct"
    echo "3. Service was restarted"
fi

echo ""
echo "=========================================="

