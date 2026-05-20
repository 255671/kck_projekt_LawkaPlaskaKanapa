# Integracja Config Service - Instrukcja dla Pythonistów

## 📋 Przegląd

System `config-service.js` zbiera ustawienia z interfejsu Electron i wysyła je do procesów Python.

```
config-service.js → renderer.js → main.js → Python procesy
```

## 📨 Jak odbierać konfigurację w Pythonie?

### 1. AUDIO SERVICE (Flask :5000)

Słucha na: **POST** `/api/config`

```python
@app.route('/api/config', methods=['POST'])
def update_config():
    """
    Odbiera konfigurację z JS
    
    Request JSON:
    {
      "config": {
        "audio": {
          "language": "pl-PL",
          "volume": 100,
          "speechRate": 150,
          "microphone_id": 0,
          "enabled": true
        },
        "cameras": {
          "front": {
            "deviceId": "camera123...",
            "enabled": true,
            "resolution": "1920x1080",
            "fps": 30,
            "ar_overlay": true
          },
          "side": {
            "deviceId": "camera456...",
            "enabled": true,
            "resolution": "1280x720",
            "fps": 30,
            "ar_overlay": true
          }
        },
        "exercise": {...},
        "calibration": {...}
      }
    }
    """
    try:
        data = request.get_json()
        config = data.get('config', {})
        
        # Wyodrębnij audio config
        audio_config = config.get('audio', {})
        
        # Aktualizuj ustawienia serwisu
        if 'language' in audio_config:
            audio_service.language = audio_config['language']
        
        if 'volume' in audio_config:
            # Volume przyjdzie jako 0-100, konwertuj do 0-1
            audio_service.volume = audio_config['volume'] / 100.0
        
        if 'speechRate' in audio_config:
            audio_service.speech_rate = audio_config['speechRate']
        
        # Informacja: AR overlay settings przychodzą w cameras, ale mogą być użyte tutaj
        cameras = config.get('cameras', {})
        if cameras.get('front', {}).get('ar_overlay'):
            logger.info("Front camera AR overlay enabled")
        
        logger.info(f"Config updated: {audio_config}")
        
        return jsonify({
            'status': 'success',
            'message': 'Config updated',
            'current_settings': {
                'language': audio_service.language,
                'volume': audio_service.volume,
                'speech_rate': audio_service.speech_rate
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error updating config: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
```

---

### 2. MEDIAPIPE SERVICE (WebSocket :8765)

Słucha na: **WebSocket message** z `type: "config"`

```python
import asyncio
import json
import logging
import websockets

logger = logging.getLogger(__name__)

async def handler(websocket, path):
    """
    Obsługuje WebSocket z Electrona
    """
    logger.info("Electron connected")
    
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                
                # Obsługuj wiadomość konfiguracyjną
                if data.get('type') == 'config':
                    config = data.get('payload', {})
                    await handle_config_update(config)
                    
                    # Wyślij potwierdzenie (opcjonalne)
                    response = {
                        'type': 'config_ack',
                        'status': 'success'
                    }
                    await websocket.send(json.stringify(response))
                    
            except json.JSONDecodeError:
                logger.warning("Failed to parse JSON from Electron")
                
    except websockets.exceptions.ConnectionClosed:
        logger.info("Electron disconnected")


async def handle_config_update(config):
    """
    Przetwarza nową konfigurację
    """
    logger.info(f"Received new config: {config}")
    
    # Wyodrębnij kamery
    cameras = config.get('cameras', {})
    front_camera = cameras.get('front', {})
    side_camera = cameras.get('side', {})
    
    # Aktualizuj ustawienia MediaPipe
    if front_camera.get('enabled'):
        logger.info(f"Front camera: {front_camera.get('resolution')} @ {front_camera.get('fps')} FPS")
        # Wyświetlaj AR overlay (punkty anatomiczne) jeśli włączone
        if front_camera.get('ar_overlay'):
            logger.info("Front camera AR overlay ENABLED - pokaż punkty MediaPipe")
        else:
            logger.info("Front camera AR overlay DISABLED - ukryj punkty MediaPipe")
    
    if side_camera.get('enabled'):
        logger.info(f"Side camera: {side_camera.get('resolution')} @ {side_camera.get('fps')} FPS")
        # Wyświetlaj AR overlay (punkty anatomiczne) jeśli włączone
        if side_camera.get('ar_overlay'):
            logger.info("Side camera AR overlay ENABLED - pokaż punkty MediaPipe")
        else:
            logger.info("Side camera AR overlay DISABLED - ukryj punkty MediaPipe")
    
    # Wyodrębnij ćwiczenie
    exercise = config.get('exercise', {})
    logger.info(f"Exercise: {exercise.get('name')}, Difficulty: {exercise.get('difficulty')}")
    
    # Wyodrębnij kalibrację
    calibration = config.get('calibration', {})
    logger.info(f"Auto-calibrate: {calibration.get('auto_calibrate')}")
```
```

---

## 🔄 Flow komunikacji

```
1. Użytkownik zmienia slider głośności
   ↓
2. config-service.js zbiera całą konfigurację z UI
   ↓
3. renderer.js wysyła przez IPC do main.js
   ↓
4. main.js rozsyła:
   - POST do Audio Service (Flask :5000/api/config)
   - WebSocket message do MediaPipe (:8765)
   ↓
5. Python service odbiera i aktualizuje ustawienia
```

---

## 📦 Struktura JSON Config

```json
{
  "audio": {
    "language": "pl-PL",      // pl-PL, en-US, en-GB, de-DE
    "volume": 100,            // 0-100
    "speechRate": 150,        // 50-300
    "microphone_id": 0,       // ID mikrofonu
    "enabled": true           // Czy audio włączone
  },
  "cameras": {
    "front": {
      "deviceId": "camera123...",  // ID urządzenia kamery
      "enabled": true,
      "resolution": "1920x1080",
      "fps": 30,
      "ar_overlay": true            // Włącz wyświetlanie punktów MediaPipe
    },
    "side": {
      "deviceId": "camera456...",
      "enabled": true,
      "resolution": "1280x720",
      "fps": 30,
      "ar_overlay": true            // Włącz wyświetlanie punktów MediaPipe
    }
  },
  "exercise": {
    "name": "bulgarian_squat",
    "difficulty": "intermediate",  // easy, intermediate, hard
    "duration": 60,                // sekundy
    "repetitions": 10              // liczba powtórzeń
  },
  "calibration": {
    "device_calibrated": false,
    "auto_calibrate": true
  }
}
```

---

## ✅ Checklist integracji

- [ ] Dodaj handler POST `/api/config` w audio_service_new.py
- [ ] Dodaj handler WebSocket dla `type: "config"` w mediapipe_service.py
- [ ] Przetestuj wysyłając request cURL:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/config \
    -H "Content-Type: application/json" \
    -d '{"config":{"audio":{"language":"pl-PL","volume":50}}}'
  ```
- [ ] Przetestuj zmianę ustawienia w UI i sprawdź czy proces Python otrzymuje update
- [ ] Dodaj logowanie zmian konfiguracji w obu serwisach

---

## 🐛 Debugging

### Sprawdź czy JS wysyła konfigurację:
```
F12 → Console → powinno być:
[ConfigService] Zebrana konfiguracja: {...}
[ConfigService] Wysyłam konfigurację do procesów Python
```

### Sprawdź czy main.js rozsyła:
```
Terminal → powinno być:
[Main IPC] Otrzymana konfiguracja z config-service.js
[Main] Audio Service POST /api/config: 200
[Main] Konfiguracja wysłana do MediaPipe
```

### Sprawdź czy Python odbiera:
```
Audio Service log:
POST /api/config - Received config update...

MediaPipe WebSocket log:
Received new config: {...}
```

---

## 💡 Tips

1. **Volume** w JS to 0-100, w Pythonie konwertuj na 0-1
2. **Language** przychodzi jako string, np. "pl-PL"
3. **FPS i resolution** są stringami
4. Konfiguracja wysyłana jest **zawsze w całości**, nie tylko zmienione pola
5. Wysyłka odbywa się **co zmianę ustawienia** w UI + **na starcie aplikacji**

---

## 🚀 Rozszerzenia

Jeśli chcesz dodać nowe pola do konfiguracji:

1. Dodaj element HTML z odpowiednim `id`:
   ```html
   <input type="checkbox" id="new-setting" />
   ```

2. Zaktualizuj `gatherConfiguration()` w config-service.js:
   ```javascript
   exercise: {
     ...
     my_new_setting: document.getElementById('new-setting')?.checked
   }
   ```

3. Obsługuj w Pythonie:
   ```python
   new_setting = config.get('exercise', {}).get('my_new_setting')
   ```

---

## ❓ FAQ

**P: Jaki format ma volumen?**
O: 0-100 (procenty) od JS, konwertuj na 0-1 w Pythonie dzieląc przez 100

**P: Czy każda zmiana powoduje wysyłkę?**
O: Tak, każda zmiana ustawienia wysyła całą konfigurację

**P: Co jeśli Audio Service jest offline?**
O: main.js loguje warning ale nie przerwie wysyłki do MediaPipe

**P: Czy mogę wysłać konfigurację ręcznie z Pythona?**
O: Nie - flow jest jednokierunkowy: UI → Python. Z Pythona możesz tylko odbierać

---

## 📞 Pytania?

Sprawdź logi w:
- Console przeglądarki (F12)
- Terminal Electrona (main.js logs)
- Terminal Python (audio i mediapipe logs)
