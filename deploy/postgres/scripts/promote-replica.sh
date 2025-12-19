#!/bin/bash
# Promote a PostgreSQL replica to primary
# Use this during failover or planned switchover

set -e

PGDATA="${PGDATA:-/var/lib/postgresql/data}"

echo "=== Promoting Replica to Primary ==="
echo "WARNING: This will make this replica a standalone primary."
echo "Ensure you have updated application connection strings before proceeding."
echo ""

# Check if this is actually a replica
if [ ! -f "$PGDATA/standby.signal" ] && [ ! -f "$PGDATA/recovery.signal" ]; then
    echo "ERROR: This does not appear to be a replica."
    echo "No standby.signal or recovery.signal found."
    exit 1
fi

# Confirm promotion
read -p "Are you sure you want to promote this replica? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Promotion cancelled."
    exit 0
fi

echo "Promoting replica..."

# Promote using pg_ctl
pg_ctl promote -D "$PGDATA"

# Wait for promotion to complete
sleep 5

# Verify promotion
if [ ! -f "$PGDATA/standby.signal" ]; then
    echo "=== Promotion successful! ==="
    echo "This server is now running as a primary."
    echo ""
    echo "Next steps:"
    echo "1. Update application connection strings to point here"
    echo "2. Set up new replicas if needed"
    echo "3. Investigate the old primary"
else
    echo "ERROR: Promotion may have failed."
    echo "Check PostgreSQL logs for details."
    exit 1
fi
