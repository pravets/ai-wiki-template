#!/bin/bash
# Общая часть STT-хелперов. Вендор-нейтрально: годится любой провайдер с
# OpenAI-совместимым POST /v1/audio/transcriptions (multipart: file, model, language).
#
# В коде НЕТ эндпоинтов, ключей и моделей — только имена переменных. Ветка
# задаётся префиксом: <PREFIX>_URL, <PREFIX>_KEY, <PREFIX>_MODEL (+ общий STT_LANG).
#
# Источники значений по приоритету:
#   1) реальное окружение;
#   2) файл конфигурации: $STT_ENV_FILE → <vault>/.env → ~/.hermes/.env,
#      где <vault> = $WIKI_VAULT (по умолчанию ~/vault).
#      Формат файла: KEY=value, по строке, без экспорта.
#
# Обязательные параметры дефолтов не имеют: отсутствие → явная ошибка (exit 1),
# а не тихая подмена провайдера или модели.

STT_VAULT="${WIKI_VAULT:-$HOME/vault}"

# Путь к файлу конфигурации (первый существующий; иначе ожидаемый по умолчанию).
stt_env_file() {
  local f
  for f in "${STT_ENV_FILE:-}" "$STT_VAULT/.env" "$HOME/.hermes/.env"; do
    [ -n "$f" ] && [ -f "$f" ] && { printf '%s' "$f"; return 0; }
  done
  printf '%s' "${STT_ENV_FILE:-$STT_VAULT/.env}"
}

_stt_raw() { # $1 = имя переменной: окружение → файл конфигурации
  local name="$1" val="${!1:-}" file
  if [ -z "$val" ]; then
    file="$(stt_env_file)"
    [ -f "$file" ] && val="$(grep -E "^${name}=" "$file" 2>/dev/null | tail -1 | cut -d= -f2-)"
  fi
  printf '%s' "$val"
}

stt_load() { # $1 = имя, $2 = устаревший алиас (опц.)
  local val; val="$(_stt_raw "$1")"
  if [ -z "$val" ] && [ -n "${2:-}" ]; then val="$(_stt_raw "$2")"; fi
  printf '%s' "$val"
}

stt_require() { # $1 = имя, $2 = подсказка, $3 = устаревший алиас (опц.)
  local val; val="$(stt_load "$1" "${3:-}")"
  if [ -z "$val" ]; then
    echo "ERROR: $1 не задан — $2" >&2
    echo "       куда положить: $(stt_env_file) (формат: $1=значение)" >&2
    exit 1
  fi
  printf '%s' "$val"
}

# stt_transcribe URL KEY MODEL INPUT OUTPUT — вызов провайдера, ответ → OUTPUT.
stt_transcribe() {
  local url="$1" key="$2" model="$3" input="$4" output="$5" lang="${STT_LANG:-}"
  local endpoint="${url%/}"
  case "$endpoint" in
    */audio/transcriptions) ;;
    *) endpoint="$endpoint/audio/transcriptions" ;;
  esac

  local body code tmp
  tmp="$(mktemp)"
  body="$(curl -sS -X POST "$endpoint" \
        -H "Authorization: Bearer $key" \
        -F "file=@$input" \
        -F "model=$model" \
        ${lang:+-F "language=$lang"} \
        -w $'\n%{http_code}' 2>&1)" || {
    echo "ERROR: запрос к STT-провайдеру не удался ($endpoint)" >&2; rm -f "$tmp"; return 1;
  }
  code="${body##*$'\n'}"; body="${body%$'\n'*}"

  if [ "${code:0:1}" != "2" ]; then
    echo "ERROR: провайдер вернул HTTP $code: $(printf '%s' "$body" | head -c 300)" >&2
    rm -f "$tmp"; return 1
  fi

  printf '%s' "$body" > "$tmp"
  python3 - "$tmp" "$output" <<'PY'
import json, sys
raw = open(sys.argv[1], encoding='utf-8').read().strip()
text = raw
try:
    d = json.loads(raw)
    if isinstance(d, dict):
        for k in ("text", "transcript", "result", "content"):
            if isinstance(d.get(k), str) and d[k].strip():
                text = d[k]; break
        else:
            text = raw
except Exception:
    pass
text = text.strip()
open(sys.argv[2], 'w', encoding='utf-8').write(text + "\n")
print(text[:300])
PY
  rm -f "$tmp"
  if [ ! -s "$output" ] || [ -z "$(tr -d '[:space:]' < "$output")" ]; then
    echo "WARN: пустой результат — модель не обслуживается провайдером или в дорожке нет речи" >&2
    return 2
  fi
}

# stt_fetch_media URL OUT — скачать звуковую дорожку публичного материала.
stt_fetch_media() {
  local url="$1" out="$2" tmpdir src
  command -v yt-dlp >/dev/null || { echo "ERROR: yt-dlp не найден" >&2; return 1; }
  tmpdir="$(mktemp -d)"
  yt-dlp -x --audio-format mp3 --no-playlist \
    -o "$tmpdir/%(id)s.%(ext)s" "$url" >/dev/null 2>&1 || {
    echo "ERROR: не удалось скачать дорожку: $url" >&2; rm -rf "$tmpdir"; return 1;
  }
  src="$(find "$tmpdir" -type f | head -1)"
  if [ -z "$src" ]; then
    echo "ERROR: yt-dlp не вернул файл для $url" >&2; rm -rf "$tmpdir"; return 1
  fi
  if command -v ffmpeg >/dev/null; then
    ffmpeg -nostdin -loglevel error -y -i "$src" -ac 1 -ar 16000 "$out" || {
      echo "ERROR: ffmpeg не смог обработать дорожку" >&2; rm -rf "$tmpdir"; return 1;
    }
  else
    cp "$src" "$out"
  fi
  rm -rf "$tmpdir"
  printf 'OK: дорожка скачана (%s байт)\n' "$(wc -c < "$out")"
}
