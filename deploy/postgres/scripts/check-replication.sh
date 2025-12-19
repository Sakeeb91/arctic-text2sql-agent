#!/bin/bash
# Check PostgreSQL replication status
# Run on primary to see connected replicas

set -e

echo "=== PostgreSQL Replication Status ==="
echo ""

# Check if we're on primary or replica
IS_REPLICA=$(psql -t -c "SELECT pg_is_in_recovery();" | tr -d ' ')

if [ "$IS_REPLICA" = "t" ]; then
    echo "This is a REPLICA server."
    echo ""
    echo "=== WAL Receiver Status ==="
    psql -c "SELECT
        status,
        sender_host,
        sender_port,
        slot_name,
        received_lsn,
        last_msg_send_time,
        last_msg_receipt_time,
        latest_end_lsn,
        latest_end_time
    FROM pg_stat_wal_receiver;"

    echo ""
    echo "=== Replication Lag ==="
    psql -c "SELECT
        CASE
            WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() THEN 0
            ELSE EXTRACT(EPOCH FROM now() - pg_last_xact_replay_timestamp())
        END AS replication_lag_seconds;"
else
    echo "This is the PRIMARY server."
    echo ""
    echo "=== Connected Replicas ==="
    psql -c "SELECT
        client_addr,
        state,
        sent_lsn,
        write_lsn,
        flush_lsn,
        replay_lsn,
        sync_state,
        reply_time
    FROM pg_stat_replication;"

    echo ""
    echo "=== Replication Slots ==="
    psql -c "SELECT
        slot_name,
        slot_type,
        active,
        restart_lsn,
        confirmed_flush_lsn
    FROM pg_replication_slots;"

    echo ""
    echo "=== Replication Lag per Replica ==="
    psql -c "SELECT
        client_addr,
        pg_wal_lsn_diff(sent_lsn, replay_lsn) as bytes_behind,
        pg_size_pretty(pg_wal_lsn_diff(sent_lsn, replay_lsn)) as lag_size
    FROM pg_stat_replication;"
fi

echo ""
echo "=== WAL Statistics ==="
psql -c "SELECT
    pg_current_wal_lsn() as current_lsn,
    pg_walfile_name(pg_current_wal_lsn()) as current_wal_file;"
