# 🏋️ Virtual Trainer - Setup Instructions

Instrukcje konfiguracji środowiska dla projektu Virtualnego Trenera.

## 📋 Wymagania wstępne

- **Python 3.11.15** (zalecana wersja)
- **Node.js 18+**
- **Git**
- **Windows 10/11** (projekt testowany na Windows)

## 🚀 Szybka konfiguracja

### 1. Sklonuj repozytorium
```bash
git clone <repository-url>
cd kck_projekt_LawkaPlaskaKanapa/projekt
```

### 2. Zainstaluj zależności Python
```bash
cd python
pip install -r requirements.txt
```

### 3. Zainstaluj zależności Node.js
```bash
# W głównym katalogu projektu
npm install

# W katalogu app
cd app
npm install
cd ..
```

### 4. Uruchom aplikację
```bash
npm start
```

## 📦 Szczegółowe instrukcje instalacji

### Python Environment Setup

1. **Utwórz virtual environment** (zalecane):
```bash
python -m venv venv
venv\Scripts\activate  # Windows
```

2. **Zainstaluj wymagane pakiety**:
```bash
pip install -r python/requirements.txt
```

#### Ważne uwagi dotyczące pakietów Python:
- **mediapipe==0.10.14** - dokładnie ta wersja (nowsze mogą mieć problemy)
- **PyAudio==0.2.13** - wymaga Visual C++ Build Tools jeśli instalacja się nie powiedzie
- **pywin32** - wymagane dla TTS na Windows

### Node.js Setup

1. **Zainstaluj zależności głównego projektu**:
```bash
npm install
```

2. **Zainstaluj zależności aplikacji Electron**:
```bash
cd app
npm install
cd ..
```

## 🔧 Rozwiązywanie problemów

### Problem: "ModuleNotFoundError" dla pakietów Python
```bash
# Upewnij się, że jesteś w virtual environment
venv\Scripts\activate

# Zainstaluj ponownie
pip install -r python/requirements.txt
```

### Problem: PyAudio installation fails
```bash
# Zainstaluj wheel dla PyAudio
pip install pipwin
pipwin install pyaudio
```

### Problem: MediaPipe installation issues
```bash
# Dla problemów z MediaPipe spróbuj:
pip install mediapipe==0.10.14 --only-binary=all
```

### Problem: Electron nie uruchamia się
```bash
# Sprawdź czy wszystkie zależności są zainstalowane
cd app
npm install
cd ..
npm install

# Uruchom ponownie
npm start
```

## 🏗️ Struktura projektu

```
projekt/
├── app/                    # Aplikacja Electron
│   ├── main.js            # Główny proces Electron
│   ├── renderer.js        # Renderer process
│   ├── index.html         # UI aplikacji
│   └── package.json       # Zależności Electron
├── python/                # Backend Python
│   ├── audio_service_new.py    # API audio
│   ├── mediapipe_service.py    # API kamery/pose detection
│   ├── requirements.txt   # Zależności Python
│   └── settings.json      # Ustawienia aplikacji
├── package.json           # Główny package.json
└── .gitignore            # Ignorowane pliki
```

## 🎯 Funkcjonalności

- **Rozpoznawanie mowy** w wielu językach
- **Synteza mowy** z konfigurowalnym głosem
- **Detekcja pozycji ciała** przez MediaPipe
- **Konfigurowalne ustawienia** audio
- **Debugowanie audio** w czasie rzeczywistym

## 📞 Kontakt

W przypadku problemów z konfiguracją środowiska, sprawdź:
1. Czy wszystkie wymagania wstępne są spełnione
2. Czy virtual environment Python jest aktywowany
3. Czy wszystkie pakiety zostały zainstalowane w odpowiednich wersjach

## 🔄 Aktualizacja środowiska

Gdy dodawane są nowe zależności:

```bash
# Python
cd python
pip freeze > requirements.txt

# Node.js - sprawdź package.json
npm install <new-package>
```

---

**✅ Po wykonaniu tych kroków środowisko powinno być gotowe do pracy!**