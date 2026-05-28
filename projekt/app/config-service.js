/**
 * =========================================================
 * CONFIG SERVICE - Zbieranie konfiguracji z UI i wysyłanie do procesów Python
 * =========================================================
 * 
 * DOKUMENTACJA:
 * 
 * Ten moduł zbiera wszystkie ustawienia z interfejsu użytkownika i wysyła je
 * do procesów Python (audio_service_new.py i mediapipe_service.py).
 * 
 * ARCHITEKTURA:
 * ─────────────────────────────────────────────────────────────
 * Electron UI (HTML/JS)
 *     ↓
 * config-service.js (zbieranie danych)
 *     ↓
 * renderer.js (wysyłanie przez IPC)
 *     ↓
 * main.js (routing do Python)
 *     ├─→ audio_service_new.py (Flask POST :5000/api/config)
 *     └─→ mediapipe_service.py (WebSocket JSON message)
 * ─────────────────────────────────────────────────────────────
 * 
 * STRUKTURA KONFIGURACJI JSON:
 * ─────────────────────────────────────────────────────────────
 * {
 *   "audio": {
 *     "language": "pl-PL",        // Język syntezy mowy
 *     "volume": 100,              // Głośność 0-100
 *     "speechRate": 150,          // Szybkość mowy 50-300
 *     "microphone_id": 0,         // ID mikrofonu
 *     "enabled": true             // Czy audio włączone
 *   },
 *   "cameras": {
 *     "enabled": true,              // Globalny switch dla kamer (front + side)
 *     "ar_overlay": true,           // Globalny toggle overlay MediaPipe dla wszystkich kamer
 *     "front": {
 *       "deviceId": "abc123...",   // ID urządzenia kamery (lub puste = domyślna)
 *       "resolution": "1920x1080",
 *       "fps": 30
 *     },
 *     "side": {
 *       "deviceId": "def456...",
 *       "resolution": "1280x720",
 *       "fps": 30
 *     }
 *   },
 *   "exercise": {
 *     "name": "bulgarian_squat",
 *     "difficulty": "intermediate",
 *     "duration": 60,
 *     "repetitions": 10
 *   },
 *   "calibration": {
 *     "device_calibrated": false,
 *     "auto_calibrate": true
 *   }
 * }
 * 
 * INTEGRACJA W PYTHONIE:
 * ─────────────────────────────────────────────────────────────
 * 
 * 1. AUDIO SERVICE (Flask :5000)
 *    Odbiera: POST /api/config
 *    JSON: { "config": { "audio": { ... }, ... } }
 *    
 *    @app.route('/api/config', methods=['POST'])
 *    def update_config():
 *        data = request.get_json()
 *        config = data.get('config', {})
 *        audio_config = config.get('audio', {})
 *        
 *        # Aktualizuj ustawienia
 *        audio_service.language = audio_config.get('language', 'pl-PL')
 *        audio_service.volume = audio_config.get('volume', 100) / 100.0
 *        audio_service.speech_rate = audio_config.get('speechRate', 150)
 *        
 *        return jsonify({'status': 'success'}), 200
 * 
 * 2. MEDIAPIPE SERVICE (WebSocket :8765)
 *    Odbiera: JSON message
 *    Format: { "type": "config", "payload": { ... } }
 *    
 *    async def handler(websocket):
 *        async for message in websocket:
 *            data = json.loads(message)
 *            if data.get('type') == 'config':
 *                config = data.get('payload', {})
 *                cameras = config.get('cameras', {})
 *                # Zaktualizuj kamery, FPS, itp
 *                print(f"New camera config: {cameras}")
 * 
 * UŻYCIE W JS:
 * ─────────────────────────────────────────────────────────────
 * 
 * // Zbierz konfigurację z UI
 * const config = gatherConfiguration();
 * console.log(config);
 * 
 * // Wyślij do procesów Python
 * await sendConfigToProcesses(config);
 * 
 * // Lub wyślij tylko do Audio Service
 * await sendConfigToAudioService(config);
 * 
 * // Lub wysłij do MediaPipe przez WebSocket
 * sendConfigToMediaPipe(config);
 * 
 * =========================================================
 */

/**
 * Zbiera konfigurację z elementów UI
 * @returns {Object} Pełna konfiguracja
 */
function gatherConfiguration() {
  const arOverlayEnabled = document.getElementById('ar-overlay-enabled')?.checked ?? true;
  const cameraPreview = document.getElementById('camera');
  const cameraPreviewSide = document.getElementById('camera-side');
  const camerasEnabled = (cameraPreview ? !cameraPreview.classList.contains('hidden') : true)
    || (cameraPreviewSide ? !cameraPreviewSide.classList.contains('hidden') : true);
  
  const config = {
    audio: {
      language: document.getElementById('language-select')?.value || 'pl-PL',
      volume: parseInt(document.getElementById('volume-slider')?.value || 100),
      speechRate: parseInt(document.getElementById('speech-rate-slider')?.value || 150),
      microphone_id: document.getElementById('mic-select')?.value || 0,
      enabled: true
    },
    cameras: {
      enabled: camerasEnabled,
      ar_overlay: arOverlayEnabled,
      front: {
        // `renderer.js` ustawia value na indeks kamery (0,1,2...) kompatybilny z OpenCV
        deviceId: document.getElementById('camera-select-front')?.value || '',
        resolution: '1920x1080',
        fps: 30
      },
      side: {
        // `renderer.js` ustawia value na indeks kamery (0,1,2...) kompatybilny z OpenCV
        deviceId: document.getElementById('camera-select-side')?.value || '',
        resolution: '1280x720',
        fps: 30
      }
    },
    exercise: {
      name: 'bulgarian_squat',
      difficulty: document.getElementById('difficulty-select')?.value || 'intermediate',
      duration: parseInt(document.getElementById('duration-input')?.value || 60),
      repetitions: parseInt(document.getElementById('repetitions-input')?.value || 10)
    },
    calibration: {
      device_calibrated: false,
      auto_calibrate: true
    }
  };

  // Debug: wyświetl na konsoli
  console.log('[ConfigService] ✓ Zebrana konfiguracja:', config);
  updateDebugPanel(config);
  
  return config;
}

/**
 * Aktualizuje debug panel w HTML   
 */
function updateDebugPanel(config) {
  const debugPanel = document.getElementById('config-debug');
  if (debugPanel) {
    debugPanel.textContent = JSON.stringify(config, null, 2);
  }
}

/**
 * Wysyła konfigurację do main.js przez IPC
 * main.js rozsyła do obu serwisów Python
 * @param {Object} config - Konfiguracja do wysłania
 */
async function sendConfigToProcesses(config) {
  try {
    console.log('[ConfigService] Wysyłam konfigurację do procesów Python');
    const result = await ipcRenderer.invoke('send-config', config);
    console.log('[ConfigService] Odpowiedź:', result);
    return result;
  } catch (error) {
    console.error('[ConfigService] Błąd:', error);
    throw error;
  }
}

/**
 * Wysyła konfigurację bezpośrednio do Audio Service (Flask)
 * Przydatne do szybkich aktualizacji bez mediapipe
 * @param {Object} config - Konfiguracja do wysłania
 */
async function sendConfigToAudioService(config) {
  try {
    console.log('[ConfigService] Wysyłam konfigurację do Audio Service');
    const response = await fetch('http://127.0.0.1:5000/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config })
    });

    if (!response.ok) {
      throw new Error(`Audio Service error: ${response.status}`);
    }

    const result = await response.json();
    console.log('[ConfigService] Audio Service gotowy:', result);
    return result;
  } catch (error) {
    console.error('[ConfigService] Błąd wysyłania do Audio Service:', error);
    throw error;
  }
}

/**
 * Wysyła konfigurację do MediaPipe przez WebSocket
 * Używany przez main.js automatycznie
 * @param {Object} config - Konfiguracja do wysłania
 */
function sendConfigToMediaPipe(config) {
  // Ta funkcja jest wywoływana przez main.js, który ma dostęp do WebSocket
  // Przesyłamy dane poprzez sendConfigToProcesses()
  console.log('[ConfigService] Config będzie wysłany do MediaPipe przez WebSocket');
  return sendConfigToProcesses(config);
}

/**
 * Dołącza event listenery do elementów UI
 * Automatycznie wysyła konfigurację po zmianach
 */
function attachConfigurationListeners() {
  const elements = [
    // Audio settings
    'language-select',
    'volume-slider',
    'speech-rate-slider',
    'mic-select',
    // Cameras
    'camera-select-front',
    'camera-select-side',
    'ar-overlay-enabled',
    // Exercise
    'difficulty-select',
    'duration-input',
    'repetitions-input'
  ];

  elements.forEach(id => {
    const element = document.getElementById(id);
    if (element) {
      element.addEventListener('change', () => {
        console.log(`[ConfigService] 📝 Zmiana w: ${id}`);
        const config = gatherConfiguration();
        sendConfigToProcesses(config).catch(error => {
          console.warn('[ConfigService] ❌ Błąd synchronizacji:', error);
        });
      });
      
      // Dla sliderów - aktualizuj również przy input event (real-time)
      if (id.includes('slider')) {
        element.addEventListener('input', () => {
          const config = gatherConfiguration();
          // Nie wysyłaj na każdy ruch - poczekaj do 'change' event
        });
      }
    }
  });

  console.log('[ConfigService] ✓ Event listenery dołączone (' + elements.length + ')');
}

/**
 * Inicjalizacja ConfigService
 * Wywoła się automatycznie na starcie aplikacji
 */
function initializeConfigService() {
  console.log('[ConfigService] Inicjalizacja');
  
  // Dołącz listenery do UI
  attachConfigurationListeners();
  
  // Wyślij początkową konfigurację po załadowaniu aplikacji
  setTimeout(() => {
    console.log('[ConfigService] Wysyłam początkową konfigurację');
    const config = gatherConfiguration();
    sendConfigToProcesses(config).catch(error => {
      console.warn('[ConfigService] Nie udało się wysłać początkowej konfiguracji:', error);
    });
  }, 1000);
}
