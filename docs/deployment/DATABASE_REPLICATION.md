# Database Replication Setup

## Overview

Arctic Text2SQL uses PostgreSQL streaming replication for high availability and read scaling. This document describes the replication architecture, setup procedures, and operational tasks.

## Architecture

```
                    ┌─────────────────────────────────────────────────────┐
                    │                   API Instances                      │
                    │                                                      │
                    │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐   │
                    │  │ API #1  │ │ API #2  │ │ API #3  │ │ API #N  │   │
                    │  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘   │
                    └───────┼──────────┼──────────┼──────────┼──────────┘
                            │          │          │          │
                            └──────────┴─────┬────┴──────────┘
                                             │
                                             ▼
                    ┌─────────────────────────────────────────────────────┐
                    │                   PgBouncer                          │
                    │               Connection Pooler                      │
                    │                                                      │
                    │  • Pool Mode: Transaction                            │
                    │  • Max Connections: 1000                             │
                    │  • Default Pool: 50                                  │
                    └────────────────────┬────────────────────────────────┘
                                         │
                          ┌──────────────┴──────────────┐
                          │                             │
                          ▼                             ▼
            ┌──────────────────────┐     ┌──────────────────────┐
            │   PRIMARY DATABASE   │     │   REPLICA DATABASE   │
            │                      │     │                      │
            │  • Writes            │────▶│  • Reads (optional)  │
            │  • Strong Consistency│     │  • Failover Ready    │
            │  • WAL Generation    │     │  • Hot Standby       │
            │                      │     │                      │
            │  Port: 5432          │     │  Port: 5433          │
            └──────────────────────┘     └──────────────────────┘
                          │                             │
                          │    Streaming Replication    │
                          └─────────────────────────────┘
```

## Components

### Primary Database

The primary database handles all write operations and generates WAL (Write-Ahead Log) records for replication.

**Configuration highlights:**
- `wal_level = replica` - Enable replication-level WAL
- `max_wal_senders = 10` - Maximum replication connections
- `max_replication_slots = 10` - Persistent replication tracking
- `synchronous_commit = on` - Data durability guarantee

### Replica Database

The replica database receives WAL records and applies them in real-time, maintaining an identical copy of the data.

**Features:**
- Hot standby for read queries
- Automatic failover capability
- Sub-second replication lag (typical)

### PgBouncer

Connection pooler that sits between applications and databases:

**Benefits:**
- Reduces database connection overhead
- Transaction-level pooling for efficiency
- Transparent failover support

## Deployment

### Quick Start

```bash
# Start HA database stack
docker-compose -f docker-compose.yml \
               -f docker-compose.db-ha.yml up -d

# Check replication status
docker exec arctic-db-primary /deploy/postgres/scripts/check-replication.sh
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_USER` | postgres | Database superuser |
| `POSTGRES_PASSWORD` | (required) | Superuser password |
| `POSTGRES_DB` | text2sql | Default database |
| `REPLICATOR_USER` | replicator | Replication user |
| `REPLICATOR_PASSWORD` | (required) | Replication password |
| `DB_PRIMARY_PORT` | 5432 | Primary exposed port |
| `DB_REPLICA_PORT` | 5433 | Replica exposed port |
| `PGBOUNCER_PORT` | 6432 | PgBouncer exposed port |

### Manual Setup

If not using Docker:

1. **Configure Primary:**
   ```bash
   # Copy configuration
   cp deploy/postgres/primary/postgresql.conf /etc/postgresql/15/main/
   cp deploy/postgres/primary/pg_hba.conf /etc/postgresql/15/main/

   # Initialize replication user
   sudo -u postgres psql << EOF
   CREATE USER replicator WITH REPLICATION ENCRYPTED PASSWORD 'secure_password';
   SELECT pg_create_physical_replication_slot('replica_slot_1');
   EOF

   # Restart PostgreSQL
   systemctl restart postgresql
   ```

2. **Initialize Replica:**
   ```bash
   # Stop PostgreSQL
   systemctl stop postgresql

   # Remove existing data
   rm -rf /var/lib/postgresql/15/main/*

   # Base backup from primary
   PGPASSWORD=secure_password pg_basebackup \
       -h primary-host \
       -U replicator \
       -D /var/lib/postgresql/15/main \
       -P -v -R -X stream -S replica_slot_1

   # Start PostgreSQL
   systemctl start postgresql
   ```

## Monitoring

### Check Replication Status

On primary:
```sql
-- Connected replicas
SELECT client_addr, state, sent_lsn, replay_lsn,
       pg_wal_lsn_diff(sent_lsn, replay_lsn) AS bytes_lag
FROM pg_stat_replication;

-- Replication slots
SELECT slot_name, active, restart_lsn
FROM pg_replication_slots;
```

On replica:
```sql
-- Replication receiver status
SELECT status, sender_host, received_lsn, latest_end_lsn
FROM pg_stat_wal_receiver;

-- Replication lag
SELECT CASE
    WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() THEN 0
    ELSE EXTRACT(EPOCH FROM now() - pg_last_xact_replay_timestamp())
END AS lag_seconds;
```

### Key Metrics

| Metric | Warning | Critical | Description |
|--------|---------|----------|-------------|
| Replication Lag | > 10s | > 60s | Time behind primary |
| Bytes Behind | > 100MB | > 1GB | WAL bytes not applied |
| Slot Lag | > 1GB | > 10GB | Unused replication slot |

### Prometheus Metrics

If using postgres_exporter:

```promql
# Replication lag in bytes
pg_stat_replication_pg_wal_lsn_diff

# Slot lag
pg_replication_slot_pg_wal_lsn_diff

# Is in recovery (1 = replica)
pg_in_recovery
```

## Failover Procedures

### Automatic Failover (with Patroni)

For production environments, consider using Patroni for automatic failover:

```yaml
# Example Patroni configuration
scope: arctic-cluster
name: postgresql-1

restapi:
  listen: 0.0.0.0:8008
  connect_address: ${POD_IP}:8008

postgresql:
  listen: 0.0.0.0:5432
  connect_address: ${POD_IP}:5432
  data_dir: /var/lib/postgresql/data

  authentication:
    replication:
      username: replicator
      password: ${REPLICATOR_PASSWORD}
    superuser:
      username: postgres
      password: ${POSTGRES_PASSWORD}
```

### Manual Failover

1. **Verify Replica is Current:**
   ```bash
   docker exec arctic-db-replica psql -c "
       SELECT pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() AS is_current;"
   ```

2. **Promote Replica:**
   ```bash
   docker exec arctic-db-replica /deploy/postgres/scripts/promote-replica.sh
   ```

3. **Update Connection String:**
   ```bash
   # Update API environment
   export DATABASE_URL=postgresql://postgres:password@db-replica:5432/text2sql
   ```

4. **Restart API Services:**
   ```bash
   docker-compose restart api
   ```

### Planned Switchover

For maintenance or testing:

1. **Pause Application Writes:**
   ```bash
   # Set application to read-only mode or pause
   ```

2. **Ensure Replica is Caught Up:**
   ```sql
   -- On primary
   SELECT pg_switch_wal();  -- Force WAL switch

   -- On replica, wait for sync
   SELECT pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn();
   ```

3. **Promote Replica:**
   ```bash
   ./deploy/postgres/scripts/promote-replica.sh
   ```

4. **Reconfigure Old Primary as Replica:**
   ```bash
   # Stop old primary
   # Clear data directory
   # Initialize as replica from new primary
   ./deploy/postgres/scripts/init-replica.sh
   ```

## Backup and Recovery

### Continuous Archiving

WAL archiving is enabled on the primary for point-in-time recovery:

```ini
archive_mode = on
archive_command = 'cp %p /var/lib/postgresql/archive/%f'
```

### Base Backup

Create a base backup for disaster recovery:

```bash
# Full backup
pg_basebackup -h db-primary -U replicator \
    -D /backup/$(date +%Y%m%d) \
    -Ft -z -P

# Verify backup
pg_verifybackup /backup/20240115
```

### Point-in-Time Recovery

To recover to a specific point:

```bash
# Create recovery.conf (PostgreSQL 11) or postgresql.auto.conf (12+)
cat > /var/lib/postgresql/data/postgresql.auto.conf << EOF
restore_command = 'cp /var/lib/postgresql/archive/%f %p'
recovery_target_time = '2024-01-15 14:30:00'
recovery_target_action = 'promote'
EOF

# Create signal file
touch /var/lib/postgresql/data/recovery.signal

# Start PostgreSQL
pg_ctl start -D /var/lib/postgresql/data
```

## Connection Pooling

### PgBouncer Configuration

Transaction-level pooling for maximum efficiency:

```ini
[databases]
text2sql = host=db-primary port=5432 dbname=text2sql

[pgbouncer]
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 50
min_pool_size = 10
reserve_pool_size = 25
```

### Application Connection

Applications should connect to PgBouncer:

```python
# Use PgBouncer port (6432) instead of direct PostgreSQL (5432)
DATABASE_URL = "postgresql://user:pass@pgbouncer:6432/text2sql"
```

## Troubleshooting

### Replication Not Starting

1. Check network connectivity:
   ```bash
   docker exec arctic-db-replica pg_isready -h db-primary
   ```

2. Verify credentials:
   ```bash
   docker exec arctic-db-replica psql -h db-primary -U replicator -c "SELECT 1"
   ```

3. Check replication slot:
   ```sql
   -- On primary
   SELECT * FROM pg_replication_slots;
   ```

### High Replication Lag

1. Check replica load:
   ```bash
   docker exec arctic-db-replica vmstat 1 5
   ```

2. Check for long-running queries:
   ```sql
   SELECT pid, now() - pg_stat_activity.query_start AS duration, query
   FROM pg_stat_activity
   WHERE state = 'active' AND now() - query_start > interval '1 minute';
   ```

3. Consider adjusting `max_standby_streaming_delay`

### Connection Pool Exhaustion

1. Check PgBouncer stats:
   ```bash
   docker exec arctic-pgbouncer psql -p 5432 pgbouncer -c "SHOW POOLS;"
   ```

2. Increase pool size if needed:
   ```bash
   DEFAULT_POOL_SIZE=100 docker-compose up -d pgbouncer
   ```

## Related Documentation

- [Architecture Overview](./ARCHITECTURE.md)
- [Database Operations Runbook](../runbooks/DATABASE.md)
- [Failover Runbook](../runbooks/INCIDENT_RESPONSE.md)
