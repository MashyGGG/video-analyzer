#!/bin/sh
set -eu
umask 077
password=$(cat /run/secrets/redis_password)
# Never put a password in argv or write it to persistent storage/logs.
case "$password" in *[!0-9a-f]*|'') echo 'Invalid Redis secret' >&2; exit 1;; esac
[ "${#password}" -eq 64 ] || { echo 'Invalid Redis secret' >&2; exit 1; }
cat > /tmp/redis.conf <<EOF
bind 0.0.0.0
protected-mode yes
port 6379
dir /data
appendonly yes
appendfsync everysec
save 60 1
requirepass $password
EOF
unset password
exec redis-server /tmp/redis.conf
