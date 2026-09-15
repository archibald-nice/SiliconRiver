#!/usr/bin/env bash
# ============================================================
# Silicon River · 每日增量同步
# 作用：把 Hugging Face / OpenRouter 的最新模型数据补齐到 DATABASE_URL 指向的库（Supabase）
#
# 用法：
#   bash scripts/daily_sync.sh              # 正常跑
#   bash scripts/daily_sync.sh --dry-run    # 只检查环境，不抓取
#
# 建议用 launchd / cron 每天定时调用本脚本（见 docs/部署手册）
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# 虚拟环境位置：默认 <项目根>/.venv，可用环境变量覆盖
VENV="${SILICON_RIVER_VENV:-${PROJECT_ROOT}/.venv}"
PYTHON="${VENV}/bin/python"

LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/daily_sync_$(date +%Y%m%d).log"

log() {
  # 同时输出到终端和日志文件
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

log "=============================================="
log "Silicon River 每日增量同步 开始"
log "=============================================="

# ---------- 前置检查 ----------
if [[ ! -x "${PYTHON}" ]]; then
  log "[失败] 找不到虚拟环境 Python：${PYTHON}"
  log "       请先创建：python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi
log "[检查] 虚拟环境 OK：${PYTHON}"

if [[ ! -f "${PROJECT_ROOT}/.env" ]]; then
  log "[失败] 缺少 .env 文件（需要 DATABASE_URL）"
  log "       请执行：cp .env.example .env 并填写 DATABASE_URL"
  exit 1
fi
log "[检查] .env OK"

if [[ ${DRY_RUN} -eq 1 ]]; then
  log "[dry-run] 环境检查通过，未执行抓取。"
  exit 0
fi

EXIT_CODE=0

# ---------- 1) Hugging Face 增量 ----------
log "→ Hugging Face 增量抓取（上限 ${HF_DAILY_FETCH_LIMIT:-200}）"
if "${PYTHON}" -m src.scraper.fetch_models_incr_day >>"${LOG_FILE}" 2>&1; then
  log "  [成功] Hugging Face 增量完成"
else
  log "  [警告] Hugging Face 增量失败，详见日志；继续处理下一个数据源"
  EXIT_CODE=1
fi

# ---------- 2) OpenRouter 增量 ----------
log "→ OpenRouter 增量抓取（上限 ${OPENROUTER_DAILY_FETCH_LIMIT:-300}）"
if "${PYTHON}" -m src.scraper.fetch_models_openrouter_incr_day >>"${LOG_FILE}" 2>&1; then
  log "  [成功] OpenRouter 增量完成"
else
  log "  [警告] OpenRouter 增量失败，详见日志"
  EXIT_CODE=1
fi

log "=============================================="
if [[ ${EXIT_CODE} -eq 0 ]]; then
  log "同步完成（全部成功）"
else
  log "同步完成（存在失败项，请查看日志）"
fi
log "日志文件：${LOG_FILE}"
log "=============================================="

exit ${EXIT_CODE}
