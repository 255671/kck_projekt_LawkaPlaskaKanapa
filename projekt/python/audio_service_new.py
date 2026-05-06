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

sys.stdout.reconfigure(encoding='utf-8')
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

flask_handler.setFormatter(
    logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
)

app.logger.handlers = []
app.logger.addHandler(flask_handler)
app.logger.setLevel(logging.INFO)

logging.getLogger('werkzeug').setLevel(logging.ERROR)

# =========================================================
# AUDIO API
# =========================================================

class VirtualTrainerAudioAPI:

    def __init__(self):

        # ====================================
        # STT
        # ====================================

        self.recognizer = sr.Recognizer()

        # Ustawienia bazowe - będą dostosowywane podczas kalibracji
        self.recognizer.energy_threshold = 300  # Wyższy próg początkowy
        self.recognizer.dynamic_energy_threshold = False
        self.recognizer.pause_threshold = 1.5  # Dłuższa pauza przed końcem frazy
        self.recognizer.non_speaking_duration = 0.5

        # ====================================
        # KALIBRACJA
        # ====================================

        self.calibrated = False
        self.ambient_noise_level = 0
        self.speech_threshold = 0

        # ====================================
        # USTAWIENIA
        # ====================================

        self.settings = {
            'language': 'pl-PL',
            'volume': 1.0,
            'speech_rate': 150
        }

        # Załaduj ustawienia z pliku
        self.load_settings()

        # ====================================
        # LOCKS
        # ====================================

        self.audio_lock = threading.Lock()

        # ====================================
        # TTS
        # ====================================

        self.tts_queue = queue.Queue()

        self.tts_thread = threading.Thread(
            target=self._tts_worker,
            daemon=True
        )

        self.tts_thread.start()

        logger.info("Audio API initialized")

    # =====================================================
    # ZARZĄDZANIE USTAWIENIAMI
    # =====================================================

    def load_settings(self):
        """Ładuje ustawienia z pliku"""
        try:
            import json
            import os

            settings_file = os.path.join(os.path.dirname(__file__), 'settings.json')
            if os.path.exists(settings_file):
                with open(settings_file, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                    self.settings.update(loaded_settings)
                logger.info(f"Ustawienia załadowane: {self.settings}")
            else:
                logger.info("Brak pliku ustawień, używam domyślnych")
        except Exception as e:
            logger.exception("Błąd ładowania ustawień")

    def save_settings(self):
        """Zapisuje ustawienia do pliku"""
        try:
            import json
            import os

            settings_file = os.path.join(os.path.dirname(__file__), 'settings.json')
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            logger.info(f"Ustawienia zapisane: {self.settings}")
        except Exception as e:
            logger.exception("Błąd zapisywania ustawień")

    def update_settings(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        """Aktualizuje ustawienia i zapisuje je"""
        try:
            # Walidacja ustawień
            if 'language' in new_settings:
                supported_languages = ['pl-PL', 'en-US', 'en-GB', 'de-DE', 'fr-FR', 'es-ES']
                if new_settings['language'] not in supported_languages:
                    return {
                        "status": "error",
                        "message": f"Nieobsługiwany język: {new_settings['language']}"
                    }

            if 'volume' in new_settings:
                volume = float(new_settings['volume'])
                if not 0.0 <= volume <= 1.0:
                    return {
                        "status": "error",
                        "message": "Głośność musi być między 0.0 a 1.0"
                    }
                new_settings['volume'] = volume

            if 'speech_rate' in new_settings:
                rate = int(new_settings['speech_rate'])
                if not 50 <= rate <= 300:
                    return {
                        "status": "error",
                        "message": "Szybkość mówienia musi być między 50 a 300"
                    }
                new_settings['speech_rate'] = rate

            # Aktualizuj ustawienia
            self.settings.update(new_settings)

            # Zapisz do pliku
            self.save_settings()

            # Zastosuj ustawienia do TTS jeśli wątek działa
            if hasattr(self, 'tts_thread') and self.tts_thread.is_alive():
                self._apply_tts_settings()

            return {
                "status": "success",
                "message": "Ustawienia zaktualizowane",
                "settings": self.settings.copy()
            }

        except Exception as e:
            logger.exception("Błąd aktualizacji ustawień")
            return {
                "status": "error",
                "message": str(e)
            }

    def _apply_tts_settings(self):
        """Zastosowuje ustawienia TTS do kolejki"""
        try:
            # Wyślij specjalny komunikat do wątku TTS żeby zaktualizować ustawienia
            self.tts_queue.put({
                "type": "settings_update",
                "volume": self.settings['volume'],
                "rate": self.settings['speech_rate']
            })
        except Exception as e:
            logger.exception("Błąd aplikowania ustawień TTS")

    # =====================================================
    # KALIBRACJA DŹWIĘKU
    # =====================================================

    def calibrate_audio(self, duration: float = 2.0) -> Dict[str, Any]:
        """
        Kalibruje poziom szumu otoczenia i ustawia optymalne progi.

        Args:
            duration: Czas kalibracji w sekundach

        Returns:
            Dict z wynikami kalibracji
        """
        with self.audio_lock:
            try:
                logger.info(f"Rozpoczynam kalibrację dźwięku ({duration}s)...")

                with sr.Microphone() as source:
                    logger.info("Mierzę poziom szumu otoczenia...")

                    # Dokładniejszy pomiar szumu
                    self.recognizer.adjust_for_ambient_noise(source, duration=duration)

                    # Zapisz poziom szumu
                    self.ambient_noise_level = self.recognizer.energy_threshold
                    logger.info(f"Poziom szumu otoczenia: {self.ambient_noise_level}")

                    # Ustaw próg dla wykrywania mowy (wyższy niż szum)
                    # Mowa powinna być co najmniej 2x głośniejsza niż szum
                    self.speech_threshold = max(
                        self.ambient_noise_level * 2.5,  # 2.5x szum
                        150  # Minimum 150
                    )

                    # Ustaw próg energii na wartość między szumem a progiem mowy
                    self.recognizer.energy_threshold = (
                        self.ambient_noise_level + self.speech_threshold
                    ) / 2

                    # Ogranicz maksymalny próg
                    self.recognizer.energy_threshold = min(
                        self.recognizer.energy_threshold,
                        800  # Max 800 aby nie być zbyt czułym
                    )

                    self.calibrated = True

                    logger.info(f"Kalibracja zakończona:")
                    logger.info(f"  - Szum otoczenia: {self.ambient_noise_level}")
                    logger.info(f"  - Próg mowy: {self.speech_threshold}")
                    logger.info(f"  - Próg energii: {self.recognizer.energy_threshold}")

                    return {
                        "status": "success",
                        "ambient_noise": self.ambient_noise_level,
                        "speech_threshold": self.speech_threshold,
                        "energy_threshold": self.recognizer.energy_threshold,
                        "message": "Kalibracja dźwięku zakończona pomyślnie"
                    }

            except Exception as e:
                logger.exception("Błąd podczas kalibracji")
                return {
                    "status": "error",
                    "message": f"Błąd kalibracji: {str(e)}"
                }

    # =====================================================
    # TTS WORKER
    # =====================================================

    def _tts_worker(self):

        logger.info("TTS worker starting...")

        pythoncom.CoInitialize()

        engine = None

        try:

            engine = pyttsx3.init('sapi5')

            # ====================================
            # POLISH VOICE
            # ====================================

            voices = engine.getProperty('voices')

            selected_voice = None

            for voice in voices:

                voice_id = voice.id.upper()

                voice_name = (
                    voice.name.upper()
                    if voice.name
                    else ''
                )

                if any(
                    x in voice_id or x in voice_name
                    for x in [
                        'PAULINA',
                        'POLISH',
                        'PL-PL'
                    ]
                ):
                    selected_voice = voice.id
                    break

            if selected_voice:

                engine.setProperty(
                    'voice',
                    selected_voice
                )

            engine.setProperty('rate', 150)
            engine.setProperty('volume', 1.0)

            # ====================================
            # KLUCZOWE
            # ====================================

            engine.startLoop(False)

            logger.info("TTS initialized successfully")

            while True:

                # ====================================
                # POMPOWANIE EVENT LOOP
                # ====================================

                engine.iterate()

                try:

                    item = self.tts_queue.get_nowait()

                except queue.Empty:

                    time.sleep(0.01)
                    continue

                if item is None:
                    break

                # Obsługa różnych typów komunikatów
                if isinstance(item, dict) and item.get('type') == 'settings_update':
                    # Aktualizacja ustawień TTS
                    try:
                        if 'volume' in item:
                            engine.setProperty('volume', item['volume'])
                        if 'rate' in item:
                            engine.setProperty('rate', item['rate'])
                        logger.info(f"TTS ustawienia zaktualizowane: volume={item.get('volume')}, rate={item.get('rate')}")
                    except Exception as e:
                        logger.exception("Błąd aktualizacji ustawień TTS")
                    continue

                text, response_queue, language = item

                try:

                    logger.info(f"TTS speaking: {text} (lang: {language})")

                    # Ustaw język głosu na podstawie języka
                    if language:
                        self._set_voice_for_language(engine, language)

                    engine.say(text)

                    # ====================================
                    # CZEKAJ AŻ SKOŃCZY
                    # ====================================

                    while engine.isBusy():

                        engine.iterate()
                        time.sleep(0.01)

                    logger.info("TTS finished")

                    response_queue.put({
                        "status": "success",
                        "message": f"Wypowiedziano: {text}"
                    })

                except Exception as e:

                    logger.exception(
                        "TTS worker error"
                    )

                    response_queue.put({
                        "status": "error",
                        "message": str(e)
                    })

        except Exception as e:

            logger.exception(
                "Failed to initialize TTS"
            )

        finally:

            try:

                if engine:
                    engine.endLoop()

            except Exception:
                pass

            pythoncom.CoUninitialize()

    # =====================================================
    # USTAWIENIE GŁOSU DLA JĘZYKA
    # =====================================================

    def _set_voice_for_language(self, engine, language: str):
        """Ustawia głos odpowiedni dla danego języka"""
        try:
            voices = engine.getProperty('voices')
            selected_voice = None

            # Mapowanie języków na preferencje głosów
            voice_preferences = {
                'pl': ['PAULINA', 'POLISH', 'PL-PL'],
                'en': ['ZIRA', 'DAVID', 'EN-US', 'EN-GB'],
                'de': ['HEDDA', 'DE-DE'],
                'fr': ['HORTENSE', 'FR-FR'],
                'es': ['HELENA', 'ES-ES']
            }

            lang_prefix = language.split('-')[0].lower()
            preferred_voices = voice_preferences.get(lang_prefix, [])

            for voice in voices:
                voice_id = voice.id.upper()
                voice_name = voice.name.upper() if voice.name else ''

                # Sprawdź czy głos pasuje do preferencji języka
                for pref in preferred_voices:
                    if pref.upper() in voice_id or pref.upper() in voice_name:
                        selected_voice = voice.id
                        break

                if selected_voice:
                    break

            if selected_voice:
                engine.setProperty('voice', selected_voice)
                logger.info(f"Ustawiono głos dla języka {language}: {selected_voice}")
            else:
                logger.warning(f"Nie znaleziono odpowiedniego głosu dla języka {language}")

        except Exception as e:
            logger.exception(f"Błąd ustawiania głosu dla języka {language}")

    # =====================================================
    # SPEAK
    # =====================================================

    def speak(
        self,
        text: str,
        language: str = None
    ) -> Dict[str, Any]:

        if not text or not text.strip():

            return {
                "status": "error",
                "message": "Brak tekstu"
            }

        # Użyj języka z parametrów lub z ustawień
        if language is None:
            language = self.settings.get('language', 'pl-PL')

        try:

            response_queue = queue.Queue()

            self.tts_queue.put(
                (
                    text,
                    response_queue,
                    language
                )
            )

            result = response_queue.get(
                timeout=60
            )

            return result

        except queue.Empty:

            return {
                "status": "error",
                "message": "TTS timeout"
            }

        except Exception as e:

            logger.exception("Speak error")

            return {
                "status": "error",
                "message": str(e)
            }

    # =====================================================
    # LISTEN
    # =====================================================

    def listen(
        self,
        timeout: int = 30,
        language: str = None,
        dynamic: bool = True
    ) -> Dict[str, Any]:

        # Użyj języka z parametrów lub z ustawień
        if language is None:
            language = self.settings.get('language', 'pl-PL')

        with self.audio_lock:

            try:

                # ====================================
                # KALIBRACJA JEŚLI POTRZEBA
                # ====================================

                if not self.calibrated:
                    logger.info("Urządzenie nie skalibrowane, wykonuję kalibrację...")
                    calib_result = self.calibrate_audio(1.0)  # Szybka kalibracja
                    if calib_result["status"] != "success":
                        return calib_result

                logger.info(
                    f"STT nasłuchiwanie (próg: {self.recognizer.energy_threshold})..."
                )

                with sr.Microphone() as source:

                    # Krótkie dostosowanie do aktualnego szumu
                    self.recognizer.adjust_for_ambient_noise(
                        source,
                        duration=0.3
                    )

                    # Zapewnij, że próg nie spadł poniżej poziomu szumu
                    if self.recognizer.energy_threshold < self.ambient_noise_level * 1.2:
                        self.recognizer.energy_threshold = self.ambient_noise_level * 1.2
                        logger.info(f"Dostosowano próg do: {self.recognizer.energy_threshold}")

                    # Maksymalny limit progu
                    if self.recognizer.energy_threshold > 1000:
                        self.recognizer.energy_threshold = 800
                        logger.warning("Próg energii zbyt wysoki, ograniczono do 800")

                    try:

                        if dynamic:
                            # Dynamiczne nasłuchiwanie - kończy po ciszy
                            logger.info("Tryb dynamiczny: czekam na mowę...")
                            audio = self.recognizer.listen(
                                source,
                                timeout=timeout,
                                phrase_time_limit=timeout
                            )
                        else:
                            # Stały timeout
                            logger.info(f"Tryb stały: nasłuchuję przez {timeout}s...")
                            audio = self.recognizer.listen(
                                source,
                                timeout=5,
                                phrase_time_limit=timeout
                            )

                        logger.info("Rozpoznaję mowę...")

                        text = self.recognizer.recognize_google(
                            audio,
                            language=language
                        )

                        # Sprawdź czy tekst wygląda na rzeczywistą mowę
                        if self._is_valid_speech(text):
                            logger.info(f"Rozpoznano prawidłową mowę: '{text}'")
                            return {
                                "status": "success",
                                "text": text
                            }
                        else:
                            logger.warning(f"Wykryto szum/podobny do mowy: '{text}'")
                            return {
                                "status": "noise_detected",
                                "message": "Wykryto dźwięk, ale nie rozpoznano jako mowa"
                            }

                    except sr.WaitTimeoutError:

                        return {
                            "status": "timeout",
                            "message": "Brak wykrycia dźwięku w czasie oczekiwania"
                        }

                    except sr.UnknownValueError:

                        return {
                            "status": "no_speech",
                            "message": "Nie udało się rozpoznać mowy"
                        }

                    except Exception as e:

                        logger.exception("Błąd nasłuchiwania")

                        return {
                            "status": "error",
                            "message": str(e)
                        }

            except Exception as e:

                logger.exception("Błąd ogólny w listen")

                return {
                    "status": "error",
                    "message": str(e)
                }

    # =====================================================
    # SPRAWDŹ CZY TO RZECZYWISTA MOWA
    # =====================================================

    def _is_valid_speech(self, text: str) -> bool:
        """
        Sprawdza czy rozpoznany tekst wygląda na rzeczywistą mowę,
        a nie na szum lub przypadkowe dźwięki.

        Args:
            text: Rozpoznany tekst

        Returns:
            True jeśli wygląda na rzeczywistą mowę
        """
        if not text or len(text.strip()) < 2:
            return False

        text_lower = text.lower().strip()

        # Sprawdź czy zawiera rzeczywiste słowa (nie same dźwięki)
        words = text_lower.split()

        # Jeśli mniej niż 1 słowo lub same krótkie dźwięki
        if len(words) < 1:
            return False

        # Sprawdź czy nie jest to tylko dźwiękonaśladowcze słowa
        noise_words = [
            'a', 'ah', 'eh', 'oh', 'uh', 'um', 'hmm', 'ha',
            'aaa', 'eee', 'ooo', 'mmm', 'hhh'
        ]

        # Jeśli wszystkie słowa to szum - odrzuć
        if all(word in noise_words for word in words):
            return False

        # Sprawdź czy nie jest to tylko pojedyncze litery lub symbole
        if len(text.strip()) <= 3 and not any(c.isalpha() for c in text):
            return False

        # Jeśli przeszło wszystkie testy - prawdopodobnie rzeczywista mowa
        return True

    # =====================================================
    # REPEAT
    # =====================================================

    def repeat_voice(
        self,
        timeout: int = 30,
        dynamic: bool = True
    ):

        result = self.listen(
            timeout=timeout,
            dynamic=dynamic
        )

        if result["status"] != "success":
            return result

        text = result["text"]

        speak_result = self.speak(text)

        if speak_result["status"] == "success":

            return {
                "status": "success",
                "original_text": text
            }

        return speak_result

# =========================================================
# GLOBAL INSTANCE
# =========================================================

audio_api = VirtualTrainerAudioAPI()

# =========================================================
# ROUTES
# =========================================================

@app.route('/health')
def health():

    return jsonify({
        "status": "ok"
    })

@app.route('/status')
def status():

    return jsonify({
        "status": "ok"
    })

@app.route('/hello')
def hello():

    logger.info("/hello")

    # Pobierz język z ustawień
    language = audio_api.settings.get('language', 'pl-PL')
    
    # Wybierz odpowiednie powitanie w zależności od języka
    greetings = {
        'pl-PL': 'Cześć',
        'en-US': 'Hello',
        'en-GB': 'Hello',
        'de-DE': 'Hallo',
        'fr-FR': 'Bonjour',
        'es-ES': 'Hola'
    }
    
    greeting = greetings.get(language, 'Hello')

    return jsonify(
        audio_api.speak(greeting, language)
    )

@app.route('/speak', methods=['POST'])
def speak():

    data = request.json

    text = data.get('text', '')
    language = data.get('language', 'pl')

    logger.info(
        f"/speak text={text}"
    )

    result = audio_api.speak(
        text,
        language
    )

    return jsonify(result)

@app.route('/listen')
def listen():

    timeout = int(
        request.args.get('timeout', 30)
    )

    language = request.args.get(
        'language',
        'pl-PL'
    )

    dynamic = (
        request.args.get(
            'dynamic',
            'true'
        ).lower() == 'true'
    )

    result = audio_api.listen(
        timeout=timeout,
        language=language,
        dynamic=dynamic
    )

    return jsonify(result)

@app.route('/repeat')
def repeat():

    timeout = int(
        request.args.get('timeout', 30)
    )

    dynamic = (
        request.args.get(
            'dynamic',
            'true'
        ).lower() == 'true'
    )

    result = audio_api.repeat_voice(
        timeout=timeout,
        dynamic=dynamic
    )

    return jsonify(result)

@app.route('/calibrate')
def calibrate():

    duration = float(
        request.args.get('duration', 2.0)
    )

    logger.info(
        f"/calibrate duration={duration}"
    )

    result = audio_api.calibrate_audio(
        duration=duration
    )

    return jsonify(result)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'GET':
        # Pobierz ustawienia
        return jsonify({
            "status": "success",
            "settings": audio_api.settings.copy()
        })
    else:
        # Zaktualizuj ustawienia
        data = request.json
        if not data:
            return jsonify({
                "status": "error",
                "message": "Brak danych ustawień"
            })

        result = audio_api.update_settings(data)
        return jsonify(result)

# =========================================================
# MAIN
# =========================================================

if __name__ == '__main__':

    logger.info(
        "Starting Audio API..."
    )

    app.run(
        host='127.0.0.1',
        port=5000,
        debug=False,
        threaded=False,
        use_reloader=False
    )