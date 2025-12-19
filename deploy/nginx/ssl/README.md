# SSL Certificate Directory

This directory should contain SSL certificates for the Nginx load balancer.

## Required Files

| File | Description |
|------|-------------|
| `server.crt` | SSL certificate (or certificate chain) |
| `server.key` | Private key (keep secure!) |
| `dhparam.pem` | Diffie-Hellman parameters |
| `ca-bundle.crt` | (Optional) CA bundle for OCSP stapling |

## Certificate Options

### Option 1: Let's Encrypt (Recommended for Production)

```bash
# Install certbot
apt-get install certbot

# Obtain certificate
certbot certonly --webroot -w /var/www/certbot \
    -d api.text2sql.example.com

# Certificates will be at:
# /etc/letsencrypt/live/api.text2sql.example.com/fullchain.pem
# /etc/letsencrypt/live/api.text2sql.example.com/privkey.pem

# Copy or symlink to this directory
ln -s /etc/letsencrypt/live/api.text2sql.example.com/fullchain.pem server.crt
ln -s /etc/letsencrypt/live/api.text2sql.example.com/privkey.pem server.key
```

### Option 2: Self-Signed (Development Only)

```bash
# Generate self-signed certificate
./scripts/generate-self-signed.sh

# Or manually:
openssl req -x509 -nodes -days 365 \
    -newkey rsa:2048 \
    -keyout server.key \
    -out server.crt \
    -subj "/CN=localhost"
```

### Option 3: Commercial Certificate

1. Generate CSR:
   ```bash
   openssl req -new -newkey rsa:2048 -nodes \
       -keyout server.key \
       -out server.csr
   ```

2. Submit CSR to certificate authority

3. Place issued certificate as `server.crt`

4. Combine with intermediate certs if needed:
   ```bash
   cat your_cert.crt intermediate.crt > server.crt
   ```

## Generate DH Parameters

DH parameters are required for strong key exchange:

```bash
# Run the generation script
./scripts/generate-dhparam.sh

# Or manually (takes 5-30 minutes):
openssl dhparam -out dhparam.pem 4096
```

## File Permissions

Ensure proper permissions for security:

```bash
chmod 644 server.crt
chmod 600 server.key
chmod 644 dhparam.pem
chown root:root server.key
```

## Verification

Verify certificate:

```bash
# Check certificate details
openssl x509 -in server.crt -text -noout

# Verify key matches certificate
openssl x509 -in server.crt -modulus -noout | md5sum
openssl rsa -in server.key -modulus -noout | md5sum
# Both should match

# Test SSL configuration
openssl s_client -connect localhost:443 -servername api.text2sql.example.com
```

## Certificate Renewal

For Let's Encrypt, set up auto-renewal:

```bash
# Add to crontab
0 0 * * * certbot renew --quiet --post-hook "nginx -s reload"
```
