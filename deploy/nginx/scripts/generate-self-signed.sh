#!/bin/bash
# Generate self-signed SSL certificate for development

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSL_DIR="$SCRIPT_DIR/../ssl"

DOMAIN="${1:-localhost}"
DAYS="${2:-365}"

echo "Generating self-signed certificate for: $DOMAIN"

# Generate private key and certificate
openssl req -x509 -nodes -days "$DAYS" \
    -newkey rsa:2048 \
    -keyout "$SSL_DIR/server.key" \
    -out "$SSL_DIR/server.crt" \
    -subj "/C=US/ST=State/L=City/O=Arctic Text2SQL/CN=$DOMAIN" \
    -addext "subjectAltName=DNS:$DOMAIN,DNS:localhost,IP:127.0.0.1"

# Set appropriate permissions
chmod 600 "$SSL_DIR/server.key"
chmod 644 "$SSL_DIR/server.crt"

echo "Certificate generated:"
echo "  - Certificate: $SSL_DIR/server.crt"
echo "  - Private Key: $SSL_DIR/server.key"
echo ""
echo "Certificate details:"
openssl x509 -in "$SSL_DIR/server.crt" -noout -subject -dates

echo ""
echo "Done! For development, you may need to add the certificate to your trusted store."
