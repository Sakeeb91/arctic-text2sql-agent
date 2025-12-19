# Database Operations Runbook

## Overview

This runbook covers database operations for Arctic Text2SQL including backups, migrations, maintenance, and disaster recovery.

## Prerequisites

- [ ] Database admin credentials
- [ ] Access to backup storage (S3/GCS)
- [ ] psql client installed
- [ ] Sufficient disk space for operations

---

## Procedure 1: Create Manual Backup

### When to Use

- Before major changes
- Before migrations
- Periodic backup verification

### Step 1: Connect to Database

```bash
# Docker
docker exec -it arctic-db-primary bash

# Kubernetes
kubectl exec -it deployment/arctic-postgres -n arctic-text2sql -- bash
```

### Step 2: Create Backup

```bash
# Full database backup
pg_dump -U postgres -d text2sql -F c -f /tmp/backup-$(date +%Y%m%d-%H%M%S).dump

# Schema only
pg_dump -U postgres -d text2sql --schema-only -f /tmp/schema-$(date +%Y%m%d).sql

# Data only
pg_dump -U postgres -d text2sql --data-only -f /tmp/data-$(date +%Y%m%d).sql
```

### Step 3: Upload to Storage

```bash
# AWS S3
aws s3 cp /tmp/backup-*.dump s3://arctic-backups/postgres/

# GCS
gsutil cp /tmp/backup-*.dump gs://arctic-backups/postgres/
```

### Step 4: Verify Backup

```bash
# List backup contents
pg_restore -l /tmp/backup-*.dump | head -20

# Test restore to temporary database
createdb -U postgres text2sql_verify
pg_restore -U postgres -d text2sql_verify /tmp/backup-*.dump
dropdb -U postgres text2sql_verify
```

---

## Procedure 2: Restore from Backup

### When to Use

- Data corruption recovery
- Disaster recovery
- Point-in-time recovery

### Step 1: Identify Backup

```bash
# List available backups
aws s3 ls s3://arctic-backups/postgres/

# Download backup
aws s3 cp s3://arctic-backups/postgres/backup-20240115-120000.dump /tmp/
```

### Step 2: Stop Application Traffic

```bash
# Scale down API
kubectl scale deployment/arctic-text2sql-api --replicas=0 -n arctic-text2sql

# Or enable maintenance mode
kubectl set env deployment/arctic-text2sql-api MAINTENANCE_MODE=true -n arctic-text2sql
```

### Step 3: Restore Database

```bash
# Drop and recreate database
psql -U postgres << EOF
DROP DATABASE IF EXISTS text2sql;
CREATE DATABASE text2sql;
EOF

# Restore from backup
pg_restore -U postgres -d text2sql -c /tmp/backup-20240115-120000.dump

# Verify tables
psql -U postgres -d text2sql -c "\dt"
```

### Step 4: Resume Service

```bash
# Scale up API
kubectl scale deployment/arctic-text2sql-api --replicas=3 -n arctic-text2sql

# Verify health
curl https://api.text2sql.example.com/api/v1/health
```

---

## Procedure 3: Run Migration

### When to Use

- Schema changes
- New version deployment
- Data model updates

### Step 1: Pre-Migration Checks

```bash
# Create backup first!
./deploy/postgres/scripts/backup.sh

# Check current migration status
docker exec arctic-api alembic current

# Review pending migrations
docker exec arctic-api alembic history --verbose
```

### Step 2: Run Migration

```bash
# Apply all pending migrations
docker exec arctic-api alembic upgrade head

# Or apply specific migration
docker exec arctic-api alembic upgrade abc123
```

### Step 3: Verify Migration

```bash
# Check new schema
psql -U postgres -d text2sql -c "\d+ table_name"

# Verify migration applied
docker exec arctic-api alembic current
```

### Step 4: Rollback (if needed)

```bash
# Rollback last migration
docker exec arctic-api alembic downgrade -1

# Rollback to specific version
docker exec arctic-api alembic downgrade abc123
```

---

## Procedure 4: Failover to Replica

### When to Use

- Primary database failure
- Planned maintenance
- Primary unavailable

### Step 1: Verify Replica Status

```bash
# Check replica is caught up
docker exec arctic-db-replica psql -U postgres -c "
  SELECT pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() AS is_current;"
```

### Step 2: Promote Replica

```bash
# Promote replica to primary
docker exec arctic-db-replica /deploy/postgres/scripts/promote-replica.sh

# Verify promotion
docker exec arctic-db-replica psql -U postgres -c "SELECT pg_is_in_recovery();"
# Should return 'f' (false)
```

### Step 3: Update Application

```bash
# Update connection string
kubectl set env deployment/arctic-text2sql-api \
  DATABASE_URL=postgresql://postgres:password@db-replica:5432/text2sql \
  -n arctic-text2sql

# Restart pods
kubectl rollout restart deployment/arctic-text2sql-api -n arctic-text2sql
```

### Step 4: Document Failover

Record in incident log:
- Time of failover
- Reason
- Data loss (if any)
- Recovery actions

---

## Procedure 5: Vacuum and Analyze

### When to Use

- Regular maintenance (weekly)
- After large deletes
- Query performance degradation

### Step 1: Check Table Bloat

```bash
psql -U postgres -d text2sql << EOF
SELECT
  schemaname || '.' || relname AS table_name,
  pg_size_pretty(pg_relation_size(relid)) AS table_size,
  n_dead_tup AS dead_tuples,
  last_vacuum,
  last_autovacuum
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC
LIMIT 10;
EOF
```

### Step 2: Run Vacuum

```bash
# Vacuum specific table
psql -U postgres -d text2sql -c "VACUUM ANALYZE table_name;"

# Vacuum entire database
psql -U postgres -d text2sql -c "VACUUM ANALYZE;"

# Full vacuum (requires exclusive lock)
# WARNING: Blocks all operations
psql -U postgres -d text2sql -c "VACUUM FULL table_name;"
```

### Step 3: Verify Results

```bash
psql -U postgres -d text2sql << EOF
SELECT
  relname AS table,
  n_dead_tup AS dead,
  n_live_tup AS live,
  last_vacuum
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC;
EOF
```

---

## Procedure 6: Connection Pool Management

### When to Use

- Connection exhaustion
- PgBouncer issues
- Pool tuning

### Step 1: Check Pool Status

```bash
# PgBouncer stats
docker exec arctic-pgbouncer psql -p 5432 pgbouncer -c "SHOW POOLS;"

# Active connections
docker exec arctic-pgbouncer psql -p 5432 pgbouncer -c "SHOW CLIENTS;"

# Database stats
docker exec arctic-pgbouncer psql -p 5432 pgbouncer -c "SHOW STATS;"
```

### Step 2: Adjust Pool Size

```bash
# Reload configuration
docker exec arctic-pgbouncer psql -p 5432 pgbouncer -c "RELOAD;"

# Or restart with new settings
docker-compose up -d pgbouncer
```

### Step 3: Kill Problematic Connections

```bash
# Kill idle connections
docker exec arctic-pgbouncer psql -p 5432 pgbouncer -c "KILL database_name;"

# Suspend database
docker exec arctic-pgbouncer psql -p 5432 pgbouncer -c "SUSPEND database_name;"
```

---

## Emergency Procedures

### Database Locked

```bash
# Find blocking queries
psql -U postgres -d text2sql << EOF
SELECT
  pid,
  usename,
  pg_blocking_pids(pid) AS blocked_by,
  query AS blocked_query
FROM pg_stat_activity
WHERE cardinality(pg_blocking_pids(pid)) > 0;
EOF

# Terminate blocking connection
psql -U postgres -d text2sql -c "SELECT pg_terminate_backend(PID);"
```

### Connection Limit Reached

```bash
# Check connection count
psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"

# Increase limit (requires restart)
# Edit postgresql.conf: max_connections = 300

# Terminate idle connections
psql -U postgres << EOF
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'text2sql'
  AND state = 'idle'
  AND state_change < current_timestamp - INTERVAL '10 minutes';
EOF
```

---

## Verification Checklist

After database operations:

- [ ] Database responding to queries
- [ ] Replication lag acceptable
- [ ] Application health checks passing
- [ ] No unusual errors in logs
- [ ] Backup verification completed

---

## Related Documentation

- [Database Replication Setup](../deployment/DATABASE_REPLICATION.md)
- [Incident Response](./INCIDENT_RESPONSE.md)
- [Troubleshooting](./TROUBLESHOOTING.md)
