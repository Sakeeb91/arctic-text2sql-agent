#!/bin/bash
# Initialize PostgreSQL replica from primary
# Run this script on a fresh replica container

set -e

# Configuration
PRIMARY_HOST="${PRIMARY_HOST:-db-primary}"
PRIMARY_PORT="${PRIMARY_PORT:-5432}"
REPLICATOR_USER="${REPLICATOR_USER:-replicator}"
REPLICATOR_PASSWORD="${REPLICATOR_PASSWORD:-replicator_password}"
REPLICATION_SLOT="${REPLICATION_SLOT:-replica_slot_1}"
PGDATA="${PGDATA:-/var/lib/postgresql/data}"

echo "=== Initializing PostgreSQL Replica ==="
echo "Primary host: $PRIMARY_HOST:$PRIMARY_PORT"

# Check if data directory is empty or needs initialization
if [ -f "$PGDATA/PG_VERSION" ]; then
    echo "Data directory already initialized. Checking if this is a replica..."
    if [ -f "$PGDATA/standby.signal" ] || [ -f "$PGDATA/recovery.signal" ]; then
        echo "This is already a replica. Exiting."
        exit 0
    else
        echo "ERROR: Data directory contains a primary database."
        echo "Please clear $PGDATA to initialize as replica."
        exit 1
    fi
fi

# Wait for primary to be ready
echo "Waiting for primary database at $PRIMARY_HOST:$PRIMARY_PORT..."
until PGPASSWORD="$REPLICATOR_PASSWORD" pg_isready -h "$PRIMARY_HOST" -p "$PRIMARY_PORT" -U "$REPLICATOR_USER"; do
    echo "Primary not ready, waiting..."
    sleep 5
done

echo "Primary is ready. Starting base backup..."

# Perform base backup from primary
PGPASSWORD="$REPLICATOR_PASSWORD" pg_basebackup \
    -h "$PRIMARY_HOST" \
    -p "$PRIMARY_PORT" \
    -U "$REPLICATOR_USER" \
    -D "$PGDATA" \
    -P \
    -v \
    -R \
    -X stream \
    -S "$REPLICATION_SLOT"

# Create standby signal file (PostgreSQL 12+)
touch "$PGDATA/standby.signal"

# Ensure proper permissions
chmod 700 "$PGDATA"

echo "=== Replica initialization complete ==="
echo "The replica will start streaming from the primary automatically."
echo ""
echo "To verify replication status on primary, run:"
echo "  SELECT * FROM pg_stat_replication;"
echo ""
echo "To verify replication status on replica, run:"
echo "  SELECT * FROM pg_stat_wal_receiver;"
