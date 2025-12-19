#!/bin/bash
# Initialize PostgreSQL primary for replication
# Run this script on the primary database container

set -e

# Configuration
REPLICATOR_USER="${REPLICATOR_USER:-replicator}"
REPLICATOR_PASSWORD="${REPLICATOR_PASSWORD:-replicator_password}"
REPLICATION_SLOT="${REPLICATION_SLOT:-replica_slot_1}"

echo "=== Initializing PostgreSQL Primary for Replication ==="

# Wait for PostgreSQL to be ready
until pg_isready -h localhost -p 5432; do
    echo "Waiting for PostgreSQL to start..."
    sleep 2
done

echo "PostgreSQL is ready. Setting up replication..."

# Create replication user
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create replication user if not exists
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_user WHERE usename = '$REPLICATOR_USER') THEN
            CREATE USER $REPLICATOR_USER WITH REPLICATION ENCRYPTED PASSWORD '$REPLICATOR_PASSWORD';
            RAISE NOTICE 'Created replication user: $REPLICATOR_USER';
        ELSE
            ALTER USER $REPLICATOR_USER WITH PASSWORD '$REPLICATOR_PASSWORD';
            RAISE NOTICE 'Updated password for replication user: $REPLICATOR_USER';
        END IF;
    END
    \$\$;

    -- Grant replication privileges
    GRANT CONNECT ON DATABASE $POSTGRES_DB TO $REPLICATOR_USER;
EOSQL

# Create replication slot
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create replication slot if not exists
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1 FROM pg_replication_slots WHERE slot_name = '$REPLICATION_SLOT'
        )
        THEN pg_create_physical_replication_slot('$REPLICATION_SLOT')
        ELSE NULL
    END;
EOSQL

echo "=== Replication setup complete ==="
echo "Replication user: $REPLICATOR_USER"
echo "Replication slot: $REPLICATION_SLOT"
echo ""
echo "To initialize a replica, run:"
echo "  pg_basebackup -h primary -D /var/lib/postgresql/data -U $REPLICATOR_USER -P -v -R -X stream -C -S $REPLICATION_SLOT"
