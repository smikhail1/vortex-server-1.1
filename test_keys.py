import os
import time
import hmac
import hashlib
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

def test_bitget_connection():
    api_key = os.getenv("BITGET_SUB_API_KEY")
    secret_key = os.getenv("BITGET_SUB_SECRET_KEY")
    passphrase = os.getenv("BITGET_SUB_PASSPHRASE")

    if not api_key or not secret_key or not passphrase:
        print("❌ Ошибка: Ключи не найдены в .env файле!")
        return

    # Эндпоинт получения баланса спота V2
    url = "https://api.bitget.com/api/v2/spot/account/assets"
    ts = str(int(time.time() * 1000))
    method = "GET"
    path = "/api/v2/spot/account/assets"
    
    # 1. Формируем строку для подписи (Timestamp + Method + Path)
    sign_str = ts + method + path
    
    # 2. Делаем HMAC-SHA256
    mac = hmac.new(secret_key.encode('utf-8'), sign_str.encode('utf-8'), hashlib.sha256)
    
    # 3. ВАЖНО: Bitget требует Base64 от бинарного хэша, а не Hex-строку!
    signature = base64.b64encode(mac.digest()).decode('utf-8')
    
    headers = {
        "ACCESS-KEY": api_key,
        "ACCESS-SIGN": signature,
        "ACCESS-PASSPHRASE": passphrase,
        "ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json"
    }
    
    print(f"--- Отправка запроса ---")
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()
        if data.get("code") == "00000":
            print("✅ ПОБЕДА! Биржа приняла ключи суб-аккаунта.")
            print(f"Твой баланс: {data.get('data')}")
        else:
            print(f"❌ БИРЖА ОТВЕРГЛА ПОДПИСЬ: {data.get('msg')} (Код: {data.get('code')})")
            print(f"Подсказка: Проверь, правильно ли введен Passphrase в .env (он регистрозависимый)")
    except Exception as e:
        print(f"❌ ОШИБКА СЕТИ: {e}")

if __name__ == "__main__":
    test_bitget_connection()
