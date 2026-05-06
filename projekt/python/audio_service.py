import pythoncom # potrzebne do inicjalizacji mikrofonu w Windows
import pyttsx3
from flask import Flask, request, jsonify
import speech_recognition as sr
import sys
import os

# obsluga polskich znakow
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
#

app = Flask(__name__)
engine = None


def init_tts_engine():
    global engine
    if engine is not None:
        return engine

    try:
        engine = pyttsx3.init('sapi5')
    except Exception:
        engine = pyttsx3.init()

    voices = engine.getProperty('voices')
    selected_voice = None
    for voice in voices:
        vid = voice.id.upper()
        vname = voice.name.upper() if voice.name else ''
        if 'PAULINA' in vid or 'PAULINA' in vname or 'PL-PL' in vid or 'PL-PL' in vname:
            selected_voice = voice.id
            break

    if selected_voice:
        engine.setProperty('voice', selected_voice)
    elif voices:
        engine.setProperty('voice', voices[0].id)

    engine.setProperty('volume', 1.0)
    engine.setProperty('rate', 150)
    return engine


def speak_text(text):
    pythoncom.CoInitialize()

    try:
        engine = init_tts_engine()
        print(f"[AUDIO SERVICE] Dostępne głosy: {[voice.name for voice in engine.getProperty('voices')]}" )
        print(f"[AUDIO SERVICE] Używam głosu: {engine.getProperty('voice')}")
        print(f"[AUDIO SERVICE] Mówię: {text}")
        engine.say(text)
        engine.runAndWait()

    except Exception as e:
        print(f"[AUDIO SERVICE] Błąd silnika: {e}")

    finally:
        pythoncom.CoUninitialize()


@app.route('/speak', methods=['POST'])
def speak():
    data = request.json
    text = data.get('text', '')

    print(f"[AUDIO SERVICE] Received text: {text}")
    speak_text(text)

    return jsonify({"status": "ok"})


@app.route('/listen', methods=['GET'])
def listen():
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 100  # Lower threshold for better sensitivity
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 0.8

    print(f"[AUDIO SERVICE] Starting listen with energy_threshold: {recognizer.energy_threshold}")

    try:
        with sr.Microphone() as source:
            print("[AUDIO SERVICE] Microphone opened, adjusting for ambient noise...")
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            print(f"[AUDIO SERVICE] Adjusted energy_threshold: {recognizer.energy_threshold}")

            try:
                print("[AUDIO SERVICE] Listening...")
                audio = recognizer.listen(source, timeout=10, phrase_time_limit=10)  # Longer timeout
                print("[AUDIO SERVICE] Audio captured, recognizing...")

                text = recognizer.recognize_google(audio, language='pl-PL')
                print(f"[AUDIO SERVICE] Recognized: {text}")
                return jsonify({"status": "ok", "text": text})

            except sr.WaitTimeoutError:
                print("[AUDIO SERVICE] Timeout - no speech detected")
                return jsonify({"status": "error", "message": "Brak wykrycia mowy w czasie oczekiwania."})
            except sr.UnknownValueError:
                print("[AUDIO SERVICE] Could not understand audio")
                return jsonify({"status": "error", "message": "Nie udało się rozpoznać mowy."})
            except Exception as e:
                print(f"[AUDIO SERVICE] Recognition error: {e}")
                return jsonify({"status": "error", "message": f"Błąd rozpoznawania: {str(e)}"})
    except OSError as e:
        print(f"[AUDIO SERVICE] Microphone error: {e}")
        return jsonify({"status": "error", "message": f"Błąd urządzenia audio: {e}"})
    except Exception as e:
        print(f"[AUDIO SERVICE] General error: {e}")
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(port=5000)