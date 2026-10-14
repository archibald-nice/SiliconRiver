#!/usr/bin/env bash
# ============================================================
# Silicon River · 本地开发数据库启停
#
# 用 .venv 里 pgserver 自带的 PostgreSQL 16 二进制，在 /tmp 起一个
# 一次性实例。不依赖 Homebrew / Docker，也不碰系统 PostgreSQL。
#
# 用法：
#   bash scripts/dev_db.sh start     # 初始化（首次）并启动
#   bash scripts/dev_db.sh stop      # 停止（数据保留）
#   bash scripts/dev_db.sh status    # 查状态
#   bash scripts/dev_db.sh reset     # 停止 + 删数据 + 重新初始化启动
#   bash scripts/dev_db.sh psql      # 进 psql 交互
#
# 环境变量：
#   SILICON_RIVER_PGDATA  数据目录，默认 /tmp/silicon-river-pgdata
#   SILICON_RIVER_PGPORT  端口，默认 55432
#
# 注意：数据目录在 /tmp，**重启机器后会丢失**。需要持久化就改 PGDATA。
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

VENV="${SILICON_RIVER_VENV:-${PROJECT_ROOT}/.venv}"
PYTHON="${VENV}/bin/python"
PGDATA="${SILICON_RIVER_PGDATA:-/tmp/silicon-river-pgdata}"
PGPORT="${SILICON_RIVER_PGPORT:-55432}"
PGLOG="${PGDATA}.log"
DB_NAME="${SILICON_RIVER_DB:-silicon_river}"
TEST_DB_NAME="${SILICON_RIVER_TEST_DB:-silicon_river_test}"

fail() { echo "[失败] $*" >&2; exit 1; }

# pgserver 把 PostgreSQL 二进制装在包目录下的 pginstall/。
# 版本号可能变，所以用 Python 现算路径，不写死 python3.12。
resolve_pgbin() {
  [[ -x "${PYTHON}" ]] || fail "找不到虚拟环境 Python：${PYTHON}
       先执行：uv venv .venv --python 3.12 && uv pip install -r requirements-dev.txt"
  local pginstall
  pginstall="$("${PYTHON}" -c 'import pathlib, pgserver; print(pathlib.Path(pgserver.__file__).parent / "pginstall")' 2>/dev/null)" \
    || fail "虚拟环境里没有 pgserver，执行：uv pip install -r requirements-dev.txt"
  PGBIN="${pginstall}/bin"
  [[ -x "${PGBIN}/pg_ctl" ]] || fail "在 ${PGBIN} 找不到 pg_ctl"
}

is_running() {
  "${PGBIN}/pg_ctl" -D "${PGDATA}" status >/dev/null 2>&1
}

init_cluster() {
  if [[ -f "${PGDATA}/PG_VERSION" ]]; then
    return 0
  fi
  echo "→ 初始化数据目录 ${PGDATA}"
  mkdir -p "${PGDATA}" || fail "无法创建 ${PGDATA}"
  "${PGBIN}/initdb" -D "${PGDATA}" -U postgres --auth=trust \
    --encoding=UTF8 --locale=C >/dev/null 2>&1 || fail "initdb 失败"
  {
    echo "# ---- Silicon River 本地开发追加配置 ----"
    echo "port = ${PGPORT}"
    echo "listen_addresses = '127.0.0.1'"
    echo "unix_socket_directories = '${PGDATA}'"
  } >> "${PGDATA}/postgresql.conf"
}

ensure_database() {
  local name="$1"
  if ! "${PGBIN}/psql" -h 127.0.0.1 -p "${PGPORT}" -U postgres -lqt 2>/dev/null \
       | cut -d'|' -f1 | grep -qw "${name}"; then
    echo "→ 创建数据库 ${name}"
    "${PGBIN}/createdb" -h 127.0.0.1 -p "${PGPORT}" -U postgres "${name}" \
      || fail "创建数据库 ${name} 失败"
  fi
}

cmd_start() {
  resolve_pgbin
  init_cluster
  if is_running; then
    echo "[已运行] ${PGDATA}"
  else
    "${PGBIN}/pg_ctl" -D "${PGDATA}" -l "${PGLOG}" \
      -o "-c config_file=${PGDATA}/postgresql.conf" start >/dev/null 2>&1 \
      || fail "启动失败，看日志：${PGLOG}"
    echo "[已启动] ${PGDATA}"
  fi
  ensure_database "${DB_NAME}"
  ensure_database "${TEST_DB_NAME}"
  cat <<EOF

本地 PostgreSQL 就绪：
  host=127.0.0.1 port=${PGPORT} user=postgres
  开发库： postgresql://postgres@127.0.0.1:${PGPORT}/${DB_NAME}
  测试库： postgresql://postgres@127.0.0.1:${PGPORT}/${TEST_DB_NAME}

初始化表结构： .venv/bin/python scripts/init_db.py
EOF
}

cmd_stop() {
  resolve_pgbin
  if is_running; then
    "${PGBIN}/pg_ctl" -D "${PGDATA}" -m fast stop >/dev/null 2>&1 || fail "停止失败"
    echo "[已停止] ${PGDATA}（数据保留）"
  else
    echo "[未运行] ${PGDATA}"
  fi
}

cmd_status() {
  resolve_pgbin
  if is_running; then
    echo "[运行中] ${PGDATA}  端口 ${PGPORT}"
    "${PGBIN}/psql" -h 127.0.0.1 -p "${PGPORT}" -U postgres -d "${DB_NAME}" \
      -c "select current_database() as db, count(*) as models from models" 2>/dev/null
  else
    echo "[未运行] ${PGDATA}"
    exit 1
  fi
}

cmd_reset() {
  resolve_pgbin
  is_running && "${PGBIN}/pg_ctl" -D "${PGDATA}" -m immediate stop >/dev/null 2>&1
  # 沙箱里 rm -rf 可能被 safe-delete 拦下，移走更可靠
  if [[ -d "${PGDATA}" ]]; then
    local trash="${PGDATA}.broken-$(date +%Y%m%d-%H%M%S)"
    mv "${PGDATA}" "${trash}" 2>/dev/null || rm -rf "${PGDATA}"
    echo "→ 旧数据目录已移走"
  fi
  cmd_start
}

cmd_psql() {
  resolve_pgbin
  exec "${PGBIN}/psql" -h 127.0.0.1 -p "${PGPORT}" -U postgres -d "${DB_NAME}"
}

case "${1:-}" in
  start)  cmd_start ;;
  stop)   cmd_stop ;;
  status) cmd_status ;;
  reset)  cmd_reset ;;
  psql)   cmd_psql ;;
  *)      echo "用法: bash scripts/dev_db.sh {start|stop|status|reset|psql}" >&2; exit 2 ;;
esac
