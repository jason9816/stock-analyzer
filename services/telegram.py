"""
Telegram Bot API client — 統一收發訊息和檔案。
"""

import logging

import requests

from config import TELEGRAM_CHAT_ID, TELEGRAM_TOKEN

logger = logging.getLogger('stock_analyzer')

_BASE_URL = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}'


def send_message(text, chat_id=None, parse_mode=None, reply_markup=None):
    """
    發送文字訊息。

    Markdown 解析失敗時自動退回純文字重送，避免格式錯誤導致訊息遺失。
    """
    chat_id = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_TOKEN or not chat_id:
        return None

    payload = {
        'chat_id': chat_id,
        'text': text[:4090],
    }
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if reply_markup:
        import json

        payload['reply_markup'] = json.dumps(reply_markup)

    try:
        resp = requests.post(
            f'{_BASE_URL}/sendMessage',
            json=payload,
            timeout=10,
        ).json()

        if not resp.get('ok') and parse_mode:
            desc = str(resp.get('description', ''))
            if 'parse' in desc.lower():
                payload.pop('parse_mode', None)
                resp = requests.post(
                    f'{_BASE_URL}/sendMessage',
                    json=payload,
                    timeout=10,
                ).json()

        if not resp.get('ok'):
            logger.warning('Telegram sendMessage 失敗: %s', resp.get('description', ''))
        return resp
    except Exception as e:
        logger.warning('Telegram 發送失敗: %s', e)
        return None


def send_file(file_path, caption='', chat_id=None, retries=2):
    """發送檔案（PDF 報告等）。

    注意：必須把整個檔案先讀成 bytes 再上傳，並帶明確 filename。
    直接把開啟的 file object 丟給 requests，urllib3 會以 chunked 方式讀檔，
    大檔（>1MB）時容易觸發 'write operation timed out'；先讀進記憶體可避免。
    連線偶有不穩，故拆開 connect/read timeout 並重試。
    """
    chat_id = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_TOKEN or not chat_id:
        return None

    import os

    with open(file_path, 'rb') as f:
        data = f.read()
    filename = os.path.basename(file_path) or 'document'

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                f'{_BASE_URL}/sendDocument',
                data={'chat_id': chat_id, 'caption': caption[:1024]},
                files={'document': (filename, data, 'application/octet-stream')},
                timeout=(10, 300),  # (連線, 讀取/上傳)
            ).json()

            if resp.get('ok'):
                return resp
            logger.warning('Telegram sendDocument 失敗: %s', resp.get('description', ''))
            return resp
        except Exception as e:
            last_err = e
            logger.warning('Telegram 檔案發送失敗（第 %d/%d 次）: %s', attempt, retries, e)

    logger.warning('Telegram 檔案發送放棄，最後錯誤: %s', last_err)
    return None


def get_updates(offset=None, timeout=30):
    """
    長輪詢取得新訊息（bot 主迴圈用）。

    Args:
        offset: 上次的 update_id + 1，避免重複處理
        timeout: 長輪詢等待秒數
    """
    if not TELEGRAM_TOKEN:
        return []

    params = {'timeout': timeout}
    if offset:
        params['offset'] = offset

    try:
        resp = requests.get(
            f'{_BASE_URL}/getUpdates',
            params=params,
            timeout=timeout + 5,
        )
        return resp.json().get('result', [])
    except Exception as e:
        logger.debug('Telegram getUpdates 失敗: %s', e)
        return []
