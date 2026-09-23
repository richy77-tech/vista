#!/bin/sh
# Vista: aggiornamento automatico del canale Telegram.
# Lo lanciano i miei heartbeat. Posta il digest max ogni 6h (VISTA_DIGEST_EVERY_H)
# e gli alert solo quando un movimento supera la soglia per la prima volta.
#
#   TG_TOKEN=... ./auto.sh
#
# Il token non sta qui dentro: lo passo io al momento del lancio.
cd "$(dirname "$0")" || exit 1
: "${TG_TOKEN:?serve TG_TOKEN}"
python3 newsbot.py --auto
