#!/bin/sh
# Synology DSM 7.1 Docker / docker-compose v1 and v2. No host Python needed.
set -eu
umask 077
PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/var/packages/Docker/target/usr/bin:$PATH"
export PATH
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
APPROVAL_BASE=${APPROVAL_BASE:-/volume1/docker/company-approval}
APPROVAL_PROJECT=${APPROVAL_PROJECT:-xenosys_approval}
export APPROVAL_BASE
case "$APPROVAL_BASE" in /*) ;; *) echo 'APPROVAL_BASE must be an absolute path.' >&2; exit 1;; esac
case "$APPROVAL_BASE" in /|/volume1|/volume1/docker|/workspace|/tmp) echo 'Use a dedicated application folder.' >&2; exit 1;; esac
case "$APPROVAL_PROJECT" in ''|*[!a-z0-9_]*|[0-9_]*) echo 'Invalid project name.' >&2; exit 1;; esac
command -v docker >/dev/null || { echo 'Docker is required.' >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo 'Docker is not accessible. On NAS, use sudo sh .../nas.sh COMMAND.' >&2; exit 1; }
if docker compose version >/dev/null 2>&1; then
    COMPOSE_MODE=v2
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_MODE=v1
elif [ -x /var/packages/Docker/target/usr/bin/docker-compose ]; then
    COMPOSE_MODE=synology
else
    echo 'Docker Compose was not found. Check the Synology Docker package.' >&2; exit 1
fi
compose() {
    case "$COMPOSE_MODE" in
        v2) docker compose -p "$APPROVAL_PROJECT" -f "$SCRIPT_DIR/compose.yml" "$@";;
        v1) docker-compose -p "$APPROVAL_PROJECT" -f "$SCRIPT_DIR/compose.yml" "$@";;
        synology) /var/packages/Docker/target/usr/bin/docker-compose -p "$APPROVAL_PROJECT" -f "$SCRIPT_DIR/compose.yml" "$@";;
    esac
}
load_config() {
    [ -f "$APPROVAL_BASE/.env" ] || { echo 'Configuration missing. Run install first.' >&2; exit 1; }
    set -a
    . "$APPROVAL_BASE/.env"
    set +a
    case "$DB_NAME" in approval_*) ;; *) echo 'Only a dedicated approval_ database is supported.' >&2; exit 1;; esac
    if [ -z "${APP_IMAGE:-}" ]; then
        [ -f "$APPROVAL_BASE/.current-image" ] || { echo 'Current image missing. Finish install first.' >&2; exit 1; }
        APP_IMAGE=$(cat "$APPROVAL_BASE/.current-image")
    fi
    export APP_IMAGE
}
wait_healthy() {
    service=$1
    tries=0
    while [ "$tries" -lt 90 ]; do
        cid=$(compose ps -q "$service")
        if [ -n "$cid" ]; then
            state=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid")
            [ "$state" != healthy ] || return 0
            restarts=$(docker inspect --format '{{.RestartCount}}' "$cid")
            [ "$restarts" -le 3 ] || break
            if [ "$state" = exited ] || [ "$state" = dead ]; then break; fi
        fi
        tries=$((tries + 1))
        sleep 2
    done
    echo "Health check failed: $service. Run nas.sh logs." >&2
    return 1
}
build_image() {
    if [ -n "${APPROVAL_PREBUILT_IMAGE:-}" ]; then
        docker image inspect "$APPROVAL_PREBUILT_IMAGE" >/dev/null
        APP_IMAGE=$APPROVAL_PREBUILT_IMAGE
        export APP_IMAGE
        return
    fi
    APP_IMAGE="company-approval-web:$(date +%Y%m%d%H%M%S)-$$"
    export APP_IMAGE
    docker build -t "$APP_IMAGE" -f "$SCRIPT_DIR/Dockerfile" "$APP_ROOT"
}
run_manage() { compose run --rm --no-deps -T web python manage.py "$@"; }
mark_current() {
    printf '%s\n' "$APP_IMAGE" > "$APPROVAL_BASE/.current-image.tmp"
    mv "$APPROVAL_BASE/.current-image.tmp" "$APPROVAL_BASE/.current-image"
}
command_name=${1:-help}
case "$command_name" in help)
    echo 'Commands: install | precheck | update | status | logs | start | stop | backup | scheduled-backup | restore FILE | rollback'
    exit 0;;
esac
mkdir -p "$APPROVAL_BASE"
if [ "$command_name" != status ] && [ "$command_name" != logs ]; then
    mkdir "$APPROVAL_BASE/.operation.lock" 2>/dev/null || { echo 'Another operation is running. Check it before removing a stale .operation.lock folder.' >&2; exit 1; }
    trap 'rmdir "$APPROVAL_BASE/.operation.lock" 2>/dev/null || true' 0
    trap 'exit 130' 1 2 15
fi
case "$command_name" in
install)
    if [ -f "$APPROVAL_BASE/.initialized" ]; then echo 'Already installed. Use update or start.'; exit 0; fi
    if [ ! -f "$APPROVAL_BASE/.env" ] && [ -d "$APPROVAL_BASE/data/mariadb/mysql" ]; then
        echo 'Existing DB data without configuration. Recover the original .env; do not initialize.' >&2; exit 1
    fi
    build_image
    docker run --rm --user 0 --entrypoint python \
        -e CONFIG_OWNER="${SUDO_UID:-$(id -u)}" \
        -e INITIAL_BIND_IP="${INITIAL_BIND_IP:-192.168.1.46}" \
        -e INITIAL_APP_PORT="${INITIAL_APP_PORT:-18080}" \
        -e INITIAL_ALLOWED_HOSTS="${INITIAL_ALLOWED_HOSTS:-192.168.1.46,localhost,127.0.0.1}" \
        -v "$APPROVAL_BASE:/target" "$APP_IMAGE" /app/deploy/nas/init_config.py
    load_config
    compose up -d db
    wait_healthy db
    run_manage migrate --noinput
    run_manage bootstrap_production --password-file /data/initial-admin-password.txt
    mark_current
    compose up -d web
    wait_healthy web
    touch "$APPROVAL_BASE/.initialized"
    docker run --rm --user 0 --entrypoint rm -v "$APPROVAL_BASE/data/app:/data" "$APP_IMAGE" -f /data/initial-admin-password.txt
    echo "Installation complete. Local trial: http://$BIND_IP:$APP_PORT"
    echo "Read $APPROVAL_BASE/initial-login.txt privately. Change the password on first login."
    echo 'Next: HTTPS, scheduled backup, and a separate backup destination.'
    ;;
precheck)
    load_config
    [ ! -f "$APPROVAL_BASE/.pending-image" ] && [ ! -f "$APPROVAL_BASE/.recovery-in-progress" ] || { echo 'Complete rollback/recovery first.' >&2; exit 1; }
    shift
    build_image
    run_manage prepare_purchase_update --check "$@"
    echo 'Precheck complete. Existing web service is still running. Reuse the same role options for update.'
    ;;
update)
    load_config
    if [ -f "$APPROVAL_BASE/.pending-image" ] || [ -f "$APPROVAL_BASE/.recovery-in-progress" ]; then
        echo 'A previous update or recovery is incomplete. Complete recovery/rollback before another update.' >&2; exit 1
    fi
    previous=$APP_IMAGE
    build_image
    next=$APP_IMAGE
    shift
    # New image reads the old schema without changing DB/account information.
    run_manage prepare_purchase_update --check "$@"
    APP_IMAGE=$previous; export APP_IMAGE
    # Build first so download/build errors do not interrupt the current service.
    compose stop web
    echo 'Web service stopped. It stays stopped if backup, migration or validation fails.'
    APP_IMAGE=$next; export APP_IMAGE
    run_manage prepare_purchase_update --capture
    APP_IMAGE=$previous; export APP_IMAGE
    backup_name=$(run_manage backup_database --kind update)
    case "$backup_name" in backup-*.zip) ;; *) echo 'Backup filename was not returned; update stopped.' >&2; exit 1;; esac
    case "$backup_name" in *[!a-zA-Z0-9._-]*) echo 'Unexpected backup output; update stopped.' >&2; exit 1;; esac
    printf '%s\n' "$previous" > "$APPROVAL_BASE/.rollback-image"
    printf '%s\n' "$backup_name" > "$APPROVAL_BASE/.rollback-backup"
    APP_IMAGE=$next; export APP_IMAGE
    printf '%s\n' "$next" > "$APPROVAL_BASE/.pending-image"
    run_manage migrate --noinput
    run_manage prepare_purchase_update --verify
    run_manage prepare_purchase_update --apply
    run_manage check
    # Updating the application must not recalculate existing leave balances.
    compose up -d web
    if ! wait_healthy web; then compose stop web; exit 1; fi
    mark_current
    rm -f "$APPROVAL_BASE/.pending-image"
    echo 'Update complete. Staff can refresh their browser. Previous image and backup are retained.'
    ;;
backup|scheduled-backup)
    load_config
    if [ "$command_name" = scheduled-backup ]; then
        if [ -f "$APPROVAL_BASE/.pending-image" ] || [ -f "$APPROVAL_BASE/.recovery-in-progress" ]; then
            echo 'Scheduled work is paused while update/recovery is incomplete.' >&2; exit 1
        fi
        run_manage sync_annual_grants
        run_manage backup_database --scheduled
    else
        run_manage backup_database
    fi
    ;;
restore|rollback)
    load_config
    if [ "$command_name" = rollback ]; then
        [ -f "$APPROVAL_BASE/.rollback-image" ] && [ -f "$APPROVAL_BASE/.rollback-backup" ] || { echo 'No recorded update to roll back.' >&2; exit 1; }
        restore_file=$(cat "$APPROVAL_BASE/.rollback-backup")
        APP_IMAGE=$(cat "$APPROVAL_BASE/.rollback-image"); export APP_IMAGE
    else
        restore_file=${2:?Specify the backup filename from the backups folder.}
    fi
    docker image inspect "$APP_IMAGE" >/dev/null
    compose stop web
    touch "$APPROVAL_BASE/.recovery-in-progress"
    echo 'Offline recovery started. Later changes are replaced by the selected backup; a safety backup is created first.'
    compose run --rm --no-deps -T -e APPROVAL_OFFLINE_RESTORE=1 tools python manage.py restore_database "$restore_file"
    run_manage check
    compose up -d web
    if ! wait_healthy web; then compose stop web; exit 1; fi
    mark_current
    rm -f "$APPROVAL_BASE/.pending-image"
    rm -f "$APPROVAL_BASE/.recovery-in-progress"
    echo 'Recovery complete. Check employees, documents and annual leave before resuming work.'
    ;;
status) load_config; compose ps;;
logs) load_config; compose logs --tail=80 web db;;
start)
    load_config
    [ ! -f "$APPROVAL_BASE/.pending-image" ] || { echo 'An update is incomplete. Use rollback or investigate before starting.' >&2; exit 1; }
    [ ! -f "$APPROVAL_BASE/.recovery-in-progress" ] || { echo 'Recovery is incomplete. Complete restore or rollback before starting.' >&2; exit 1; }
    compose up -d db
    wait_healthy db
    compose up -d web
    wait_healthy web
    ;;
stop) load_config; compose stop web;;
*) echo 'Unknown command. Run nas.sh help.' >&2; exit 1;;
esac
