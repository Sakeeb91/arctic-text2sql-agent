#!/bin/bash
# Generate Diffie-Hellman parameters for SSL

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSL_DIR="$SCRIPT_DIR/../ssl"

echo "Generating DH parameters (this may take several minutes)..."

# Generate 4096-bit DH parameters (most secure, but slow)
# Use 2048 for faster generation if needed
openssl dhparam -out "$SSL_DIR/dhparam.pem" 4096

echo "DH parameters generated at: $SSL_DIR/dhparam.pem"

# Set appropriate permissions
chmod 644 "$SSL_DIR/dhparam.pem"

echo "Done!"
