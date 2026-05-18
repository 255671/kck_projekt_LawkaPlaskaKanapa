import os
import json
import pythoncom
import pyttsx3
from flask import Flask, request, jsonify
import speech_recognition as sr
import sys
import logging
from typing import Dict, Any
import threading
import queue
import time

# =========================================================
# UTF-8
# =========================================================
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# =========================================================
# LOGGING
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
    encoding='utf-8',
    force=True
)
logger = logging.getLogger(__name__)

# =========================================================
# FLASK
# =========================================================
app = Flask(__name__)

flask_handler = logging.StreamHandler(sys.stdout)
flask_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
app.logger.handlers = []
app.logger.addHandler(flask_handler)
app.logger.setLevel(logging.INFO)
logging.getLogger('werkzeug').setLevel(logging.ERROR)


# =========================================================
# AUDIO API CLASS
# =========================================================
class VirtualTrainerAudioAPI:
    def __init__(self):
        # --- STT Setup ---
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = False
        self.recognizer.pause_threshold = 1.5
        self.recognizer.non_speaking_duration = 0.5

        # --- Kalibracja Setup ---
        self.calibrated = False
        self.ambient_noise_level = 0
        self.speech_threshold = 0

        # --- Ustawienia ---
        self.settings = {
            'language': 'pl-PL',
            'volume': 1.0,
            'speech_rate': 150
        }
        self.load_settings()

        # --- Locks i Wątki ---
        self.audio_lock = threading.RLock()
        self.tts_queue = queue.Queue()
        self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.tts_thread.start()

        logger.info("Audio API initialized")

    # =====================================================
    # ZARZĄDZANIE USTAWIENIAMI
    # =====================================================
    def load_settings(self):
        try:
            settings_file = os.path.join(os.path.dirname(__file__), 'settings.json')
            if os.path.exists(settings_file):
                with open(settings_file, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                    self.settings.update(loaded_settings)
                logger.info(f"Ustawienia zaladowane: {self.settings}")
        except Exception as e:
            logger.exception("Blad ladowania ustawien")

    def save_settings(self):
        try:
            settings_file = os.path.join(os.path.dirname(__file__), 'settings.json')
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            logger.info(f"Ustawienia zapisane: {self.settings}")
        except Exception as e:
            logger.exception("Blad zapisywania ustawien")

    def update_settings(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if 'language' in new_settings:
                self.settings['language'] = new_settings['language']
            if 'volume' in new_settings:
                self.settings['volume'] = max(0.0, min(1.0, float(new_settings['volume'])))
            if 'speech_rate' in new_settings:
                self.settings['speech_rate'] = max(50, min(300, int(new_settings['speech_rate'])))

            self.save_settings()

            if hasattr(self, 'tts_thread') and self.tts_thread.is_alive():
                self._apply_tts_settings()

            return {"status": "success", "message": "Ustawienia zaktualizowane", "settings": self.settings.copy()}
        except Exception as e:
            logger.exception("Blad aktualizacji ustawien")
            return {"status": "error", "message": str(e)}

    def _apply_tts_settings(self):
        try:
            self.tts_queue.put({
                "type": "settings_update",
                "volume": self.settings['volume'],
                "rate": self.settings['speech_rate']
            })
        except Exception:
            logger.exception("Blad aplikowania ustawien TTS")

    # =====================================================
    # KALIBRACJA
    # =====================================================
    def calibrate_audio(self, duration: float = 2.0) -> Dict[str, Any]:
        with self.audio_lock:
            try:
                logger.info(f"Rozpoczynam kalibracje dzwieku ({duration}s)...")
                with sr.Microphone() as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=duration)
                    self.ambient_noise_level = self.recognizer.energy_threshold
                    self.speech_threshold = max(self.ambient_noise_level * 2.5, 150)
                    self.recognizer.energy_threshold = min((self.ambient_noise_level + self.speech_threshold) / 2, 800)

                    self.calibrated = True
                    logger.info("Kalibracja zakonczona pomyslnie.")
                    return {
                        "status": "success",
                        "ambient_noise": self.ambient_noise_level,
                        "speech_threshold": self.speech_threshold,
                        "energy_threshold": self.recognizer.energy_threshold
                    }
            except Exception as e:
                logger.exception("Blad podczas kalibracji")
                return {"status": "error", "message": str(e)}

    # =====================================================
    # TTS WORKER
    # =====================================================
    def _tts_worker(self):
        logger.info("TTS worker starting...")
        pythoncom.CoInitialize()
        engine = None
        try:
            engine = pyttsx3.init('sapi5')
            engine.setProperty('rate', self.settings.get('speech_rate', 150))
            engine.setProperty('volume', self.settings.get('volume', 1.0))
            engine.startLoop(False)

            while True:
                engine.iterate()
                try:
                    item = self.tts_queue.get_nowait()
                except queue.Empty:
                    time.sleep(0.01)
                    continue

                if item is None:
                    break

                if isinstance(item, dict) and item.get('type') == 'settings_update':
                    try:
                        if 'volume' in item: engine.setProperty('volume', item['volume'])
                        if 'rate' in item: engine.setProperty('rate', item['rate'])
                    except Exception:
                        pass
                    continue

                text, response_queue, language = item
                try:
                    logger.info(f"TTS speaking: {text}")
                    if language:
                        self._set_voice_for_language(engine, language)

                    engine.say(text)
                    while engine.isBusy():
                        engine.iterate()
                        time.sleep(0.01)

                    response_queue.put({"status": "success"})
                except Exception as e:
                    response_queue.put({"status": "error", "message": str(e)})

        finally:
            try:
                if engine: engine.endLoop()
            except Exception:
                pass
            pythoncom.CoUninitialize()

    def _set_voice_for_language(self, engine, language: str):
        try:
            voices = engine.getProperty('voices')
            lang_prefix = language.split('-')[0].lower()

            voice_preferences = {
                'pl': ['PAULINA', 'POLISH', 'PL-PL'],
                'en': ['ZIRA', 'DAVID', 'EN-US', 'EN-GB']
            }
            preferred_voices = voice_preferences.get(lang_prefix, [])

            for voice in voices:
                if any(pref in voice.id.upper() or (voice.name and pref in voice.name.upper()) for pref in
                       preferred_voices):
                    engine.setProperty('voice', voice.id)
                    break
        except Exception:
            pass

    def speak(self, text: str, language: str = None) -> Dict[str, Any]:
        if not text or not text.strip():
            return {"status": "error", "message": "Brak tekstu"}

        language = language or self.settings.get('language', 'pl-PL')
        try:
            response_queue = queue.Queue()
            self.tts_queue.put((text, response_queue, language))
            return response_queue.get(timeout=60)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # =====================================================
    # LISTEN
    # =====================================================
    def listen(self, timeout: int = 30, language: str = None, dynamic: bool = True) -> Dict[str, Any]:
        language = language or self.settings.get('language', 'pl-PL')

        logger.info("[STT] Oczekuje na zwolnienie blokady audio...")
        with self.audio_lock:
            try:
                if not self.calibrated:
                    logger.info("[STT] Brak kalibracji, uruchamiam kalibracje...")
                    self.calibrate_audio(1.0)

                logger.info("[STT] Probuje otworzyc strumien mikrofonu...")
                with sr.Microphone() as source:
                    # Delikatne dostosowanie progu, ale bez nadpisywania głównej kalibracji

                    if self.recognizer.energy_threshold < self.ambient_noise_level * 1.2:
                        self.recognizer.energy_threshold = self.ambient_noise_level * 1.2

                    logger.info(f"[STT] Mikrofon otwarty. Prog energii: {self.recognizer.energy_threshold}")

                    try:
                        #wait_timeout = 10
                        logger.info(f"[STT] Zaczynam nagrywac (max 10s)...")

                        audio = self.recognizer.listen(
                            source,
                            timeout=5,
                            phrase_time_limit=10
                        )

                        logger.info("[STT] Wysylam zapytanie do serwerow Google...")
                        text = self.recognizer.recognize_google(audio, language=language)

                        logger.info(f"[STT] Google zwrocilo wynik: '{text}'")

                        if self._is_valid_speech(text):
                            return {"status": "success", "text": text}
                        else:
                            return {"status": "noise_detected",
                                    "message": "Wykryto dźwięk, ale nie rozpoznano jako mowa."}

                    except sr.WaitTimeoutError:
                        logger.warning("[STT] Timeout - nikt nic nie powiedzial przez 5s.")
                        return {"status": "timeout", "message": "Brak mowy."}
                    except sr.UnknownValueError:
                        logger.warning("[STT] Google nic nie zrozumialo (sam szum).")
                        return {"status": "no_speech", "message": "Nie zrozumiano."}

            except Exception as e:
                logger.error(f"[STT] Blad krytyczny nasluchiwania: {str(e)}")
                return {"status": "error", "message": str(e)}

    def _is_valid_speech(self, text: str) -> bool:
        if not text or len(text.strip()) < 2: return False
        words = text.lower().strip().split()
        noise_words = ['a', 'ah', 'eh', 'oh', 'uh', 'um', 'hmm', 'ha', 'aaa', 'eee', 'ooo', 'mmm']
        if all(word in noise_words for word in words): return False
        return True


# =========================================================
# GLOBAL INSTANCE & ROUTES
# =========================================================
audio_api = VirtualTrainerAudioAPI()


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'GET':
        return jsonify({"status": "success", "settings": audio_api.settings.copy()})
    else:
        return jsonify(audio_api.update_settings(request.json or {}))


@app.route('/speak', methods=['POST'])
def speak():
    data = request.json
    return jsonify(audio_api.speak(data.get('text', ''), data.get('language')))


@app.route('/listen', methods=['GET'])
def listen():
    return jsonify(audio_api.listen(
        timeout=int(request.args.get('timeout', 30)),
        language=request.args.get('language', 'pl-PL'),
        dynamic=(request.args.get('dynamic', 'true').lower() == 'true')
    ))


@app.route('/calibrate', methods=['GET'])
def calibrate():
    return jsonify(audio_api.calibrate_audio(float(request.args.get('duration', 2.0))))


if __name__ == '__main__':
    logger.info("Starting Audio API...")
    # threaded=True jest krytyczne dla równoległych żądań w Flasku!
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True, use_reloader=False)