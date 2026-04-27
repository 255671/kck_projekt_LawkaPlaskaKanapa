import pythoncom #potrzebne do inicjalizacji mikrofonu w Windows
import pyttsx3
from flask import Flask, request, jsonify
import speech_recognition as sr
import sys

#obsluga polskich znakow
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
#

app = Flask(__name__)

def speak_text(text):
    pythoncom.CoInitialize()

    try:
        engine = pyttsx3.init()
        engine.setProperty('voice',
                           r'HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens\TTS_MS_PL-PL_PAULINA_11.0')
        # 'HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens\TTS_MS_EN-GB_HAZEL_11.0' eng

        print(f"[AUDIO SERVICE] Mówie: {text}")
        engine.say(text)
        engine.runAndWait()

    except RuntimeError as e:
        print(f"[AUDIO SERVICE] Bląd silnika: {e}")

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
    recognizer.energy_threshold = 1500

    with sr.Microphone() as source:
        print("[AUDIO SERVICE] Kalibracja...")
        recognizer.adjust_for_ambient_noise(source, duration=0.5)

        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
            text = recognizer.recognize_google(audio, language='pl-PL')

            print(f"[AUDIO SERVICE] Uslyszano: {text}")
            return jsonify({"status": "ok", "text": text})

        except sr.WaitTimeoutError:
            return jsonify({"status": "error", "message": "Nikt nic nie powiedział."})
        except sr.UnknownValueError:
            return jsonify({"status": "error", "message": "Nie zrozumiano audio."})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(port=5000)