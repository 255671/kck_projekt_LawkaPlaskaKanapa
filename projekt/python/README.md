# Virtual Trainer Audio API

Modularne API dla obsługi audio w aplikacji Virtualnego Trenera, zbudowane z myślą o przyszłej rozszerzalności.

## Funkcjonalności

- **Text-to-Speech (TTS)** - zamiana tekstu na mowę
- **Speech-to-Text (STT)** - rozpoznawanie mowy z mikrofonu
- **Konfigurowalne ustawienia** - różne języki, timeouty
- **Obsługa błędów** - szczegółowe komunikaty o błędach

## Architektura

### Klasa VirtualTrainerAudioAPI

Główna klasa API zawierająca wszystkie funkcjonalności audio:

```python
class VirtualTrainerAudioAPI:
    def __init__(self):
        # Inicjalizacja TTS i STT

    def speak(self, text: str, language: str = 'pl') -> Dict[str, Any]:
        # Zamiana tekstu na mowę

    def listen(self, timeout: int = 10, language: str = 'pl-PL') -> Dict[str, Any]:
        # Rozpoznawanie mowy
```

## API Endpoints

### GET /status
Sprawdza status API
```json
{
  "status": "ok",
  "message": "Virtual Trainer Audio API działa poprawnie",
  "features": ["TTS", "STT"],
  "languages": ["pl-PL", "en-US"]
}
```

### POST /speak
Zamienia tekst na mowę
```json
// Request
{
  "text": "Witaj świecie",
  "language": "pl"
}

// Response
{
  "status": "success",
  "message": "Wypowiedziano: Witaj świecie"
}
```

### GET /listen
Rozpoznaje mowę z mikrofonu
```json
// Request: /listen?timeout=10&language=pl-PL

// Response
{
  "status": "success",
  "text": "rozpoznany tekst",
  "confidence": null
}
```

## Status Codes

- `success` - operacja zakończona sukcesem
- `timeout` - brak wykrycia mowy w czasie oczekiwania
- `no_speech` - nie udało się rozpoznać mowy
- `error` - błąd aplikacji lub urządzenia

## Konfiguracja

### Ustawienia STT
- `energy_threshold`: 50 (niższy próg dla lepszej czułości)
- `dynamic_energy_threshold`: True
- `pause_threshold`: 0.8 sekundy
- `non_speaking_duration`: 0.5 sekundy

### Języki
- Polski: `pl-PL` (rozpoznawanie), `pl` (mówienie)
- Angielski: `en-US` (rozpoznawanie), `en` (mówienie)

## Rozszerzalność

API zostało zaprojektowane z myślą o przyszłej rozbudowie:

1. **Nowe języki** - dodaj obsługę w metodach `speak()` i `listen()`
2. **Nowe funkcjonalności** - dodaj metody do klasy `VirtualTrainerAudioAPI`
3. **Inne silniki TTS/STT** - zamień implementację w `_init_tts_engine()`
4. **Buforowanie audio** - dodaj cache dla często używanych fraz
5. **Wielowątkowość** - dodaj async/await dla równoległego przetwarzania

## Wymagania

- Python 3.11+
- speech_recognition
- pyttsx3
- Flask
- pyaudio (wymagany przez speech_recognition)

## Uruchamianie

```bash
python audio_service_new.py
```

API będzie dostępne na `http://127.0.0.1:5000`

## Debugowanie

- Szczegółowe logi w konsoli Python
- Status API dostępny przez `/status`
- Obsługa błędów z szczegółowymi komunikatami
- Monitorowanie poziomu dźwięku w aplikacji Electron</content>
<parameter name="filePath">c:\Users\Jakub\Desktop\Studia\kck\kck_projekt_LawkaPlaskaKanapa\projekt\README.md