#!/bin/sh
set -eu
umask 077
cd /opt/myapp/ugc-ops
exec /usr/bin/python3 backup_recovery.py \
    --recipient recipient.txt \
    --age bin/age \
    --image "$(cat recovery-image-id)" \
    --output-directory recovery-archives
