const { ipcRenderer } = require('electron');
const audioServiceUrl = 'http://127.0.0.1:5000';

// =========================================================
// CONFIG SERVICE INTEGRATION
// =========================================================
// Załaduj config-service.js przed użyciem
// Inicjalizacja po załadowaniu DOM (patrz na koniec pliku)

// Flaga do zapobiegania jednoczesnym operacjom audio
let isAudioOperationInProgress = false;

// Domyślne ustawienia
const defaultSettings = {
  language: 'pl-PL',
  volume: 100,
  speechRate: 150
};

// Funkcje zarządzania ustawieniami
function loadSettings() {
  try {
    const settings = localStorage.getItem('virtualTrainerSettings');
    return settings ? JSON.parse(settings) : { ...defaultSettings };
  } catch (error) {
    console.error('Błąd ładowania ustawień:', error);
    return { ...defaultSettings };
  }
}

function saveSettings(settings) {
  try {
    localStorage.setItem('virtualTrainerSettings', JSON.stringify(settings));
    console.log('Ustawienia zapisane:', settings);
  } catch (error) {
    console.error('Błąd zapisywania ustawień:', error);
  }
}

function applySettingsToUI(settings) {
  document.getElementById('language-select').value = settings.language;
  document.getElementById('volume-slider').value = settings.volume;
  document.getElementById('volume-display').textContent = settings.volume + '%';
  document.getElementById('speech-rate-slider').value = settings.speechRate;
  document.getElementById('speech-rate-display').textContent = settings.speechRate;
}

// Helper do fetch z timeoutem
async function fetchWithTimeout(url, options = {}, timeoutMs = 45000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error(`Timeout: operacja trwała dłużej niż ${timeoutMs}ms`);
    }
    throw error;
  }
}

ipcRenderer.on('mediapipe-data', (event, data) => {
  console.log('Received from Python:', data);

  if (data.image) {
    document.getElementById('camera').src = 'data:image/jpeg;base64,' + data.image;
    if (data.imageSide) {
      document.getElementById('camera-side').src = 'data:image/jpeg;base64,' + data.imageSide;
    }

    // UI: licznik powtórzeń
    try {
      const repCountEl = document.getElementById('rep-count');
      const repPhaseEl = document.getElementById('rep-phase');
      if (repCountEl && data.exercise && typeof data.exercise.repCount === 'number') {
        repCountEl.textContent = String(data.exercise.repCount);
      }
      if (repPhaseEl && data.exercise && typeof data.exercise.phase === 'string') {
        repPhaseEl.textContent = data.exercise.phase || '--';
      }
    } catch {
      // ignore
    }

    // Debug: wypisz wykrywanie ćwiczenia do logów (z throttlingiem)
    try {
      const output = document.getElementById('output');
      if (output && data.exercise && typeof data.exercise.repCount === 'number') {
        const now = Date.now();
        if (!window.__lastExerciseLogAt) window.__lastExerciseLogAt = 0;
        if ((now - window.__lastExerciseLogAt) > 1000) {
          window.__lastExerciseLogAt = now;
          const m = data.exercise.metrics;
          const metricText = m ? ` angle=${m.kneeAngle} leg=${m.leg}` : '';
          output.innerText += `\n[Exercise] ${data.exercise.name} reps=${data.exercise.repCount} phase=${data.exercise.phase}${metricText}`;
          output.scrollTop = output.scrollHeight;
        }
      }
    } catch {
      // ignore
    }
  } else {
    // W tej uproszczonej wersji logi lądują w textarea
    const output = document.getElementById('output');
    output.innerText += '\n' + JSON.stringify(data);
    output.scrollTop = output.scrollHeight;
  }
});

const speakBtn = document.getElementById('speak-btn');
const speechOutput = document.getElementById('speech-output');

//obsluga przycisku czytania (text to speech)
if(speakBtn && speechOutput) {
    speakBtn.addEventListener('click', async () => {
    if (isAudioOperationInProgress) {
        console.log("Operacja audio już w trakcie, czekaj...");
        return;
    }

    const textToSay = speechOutput.value.trim();

    if (textToSay === "") {
        console.log("Pole tekstowe jest puste, nie ma czego czytać.");
        return;
    }

    // Wyczyść linie zawierające [Info] i undefined
    const cleanText = textToSay
        .split('\n')
        .filter(line => !line.includes('[Info]') && !line.includes('undefined'))
        .join(' ')
        .trim();

    if (cleanText === "") {
        console.log("Brak czystego tekstu do przeczytania.");
        return;
    }

    isAudioOperationInProgress = true;
    speakBtn.disabled = true;
    speakBtn.innerText = "Mówię...";

    try {
        // Pobierz aktualne ustawienia języka
        const currentSettings = loadSettings();
        //tekst do Pythona
        const response = await fetchWithTimeout(`${audioServiceUrl}/speak`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            text: cleanText,
            language: currentSettings.language
        })
        }, 10000);

        if (!response.ok) {
        const body = await response.text();
        throw new Error(`Błąd serwera audio: ${response.status} ${body}`);
        }

        const data = await response.json();
        console.log("Wysłano tekst do przeczytania.", data);
    } catch (error) {
        console.error("Błąd połączenia z serwerem Flask:", error);
        speechOutput.value += `\n[Błąd]: Nie udało się przeczytać tekstu: ${error.message}`;
    } finally {
        isAudioOperationInProgress = false;
        speakBtn.disabled = false;
        speakBtn.innerText = "Przeczytaj tekst";
    }
    });
}

//obsługa przycisku kalibracji dźwięku
const calibrateBtn = document.getElementById('calibrate-btn');
if(calibrateBtn && speechOutput) {
    calibrateBtn.addEventListener('click', async () => {
    if (isAudioOperationInProgress) {
        console.log("Operacja audio już w trakcie, czekaj...");
        return;
    }

    isAudioOperationInProgress = true;
    calibrateBtn.disabled = true;
    calibrateBtn.innerText = "Kalibruję dźwięk...";

    try {
        const response = await fetchWithTimeout(`${audioServiceUrl}/calibrate?duration=2.0`, {}, 15000);
        if (!response.ok) {
        const body = await response.text();
        throw new Error(`Błąd serwera audio: ${response.status} ${body}`);
        }

        const data = await response.json();
        console.log("Odpowiedź /calibrate:", data);
        if (data.status === 'success') {
        speechOutput.value += `\n✓ Kalibracja zakończona pomyślnie`;
        speechOutput.value += `\n  - Szum otoczenia: ${data.ambient_noise}`;
        speechOutput.value += `\n  - Próg mowy: ${data.speech_threshold}`;
        speechOutput.value += `\n  - Próg energii: ${data.energy_threshold}`;
        } else {
        speechOutput.value += `\n✗ Błąd kalibracji: ${data.message}`;
        }
    } catch (error) {
        speechOutput.value += `\n[Błąd kalibracji]: ${error.message}`;
        console.error("Błąd /calibrate:", error);
    } finally {
        isAudioOperationInProgress = false;
        calibrateBtn.disabled = false;
        calibrateBtn.innerText = "Kalibruj dźwięk";
        speechOutput.scrollTop = speechOutput.scrollHeight;
    }
    });
}

const listenBtn = document.getElementById('listen-btn');

//obsluga klikniecia przycisku do nasluchiwania (speech to text)
if(listenBtn && speechOutput) {
    listenBtn.addEventListener('click', async () => {
    if (isAudioOperationInProgress) {
        console.log("Operacja audio już w trakcie, czekaj...");
        return;
    }

    speechOutput.scrollTop = speechOutput.scrollHeight;
    isAudioOperationInProgress = true;
    listenBtn.disabled = true;
    listenBtn.innerText = "Nasłuchuję...";

    try {
        // Pobierz aktualne ustawienia języka
        const currentSettings = loadSettings();
        // zapytanie do serwera flask z dynamicznym nasłuchiwaniem
        const response = await fetchWithTimeout(`${audioServiceUrl}/listen?dynamic=true&timeout=30&language=${currentSettings.language}`, {}, 45000);
        if (!response.ok) {
        const body = await response.text();
        throw new Error(`Błąd serwera audio: ${response.status} ${body}`);
        }
        const data = await response.json();

        if (data.status === 'success') {
        speechOutput.value += `\nTy: ${data.text}`;
        } else {
        speechOutput.value += `\n[Info]: ${data.message}`;
        }
    } catch (error) {
        speechOutput.value += `\n[Błąd]: ${error.message}. Upewnij się, że audio_service.py działa.`;
        console.error("Błąd /listen:", error);
    } finally {
        isAudioOperationInProgress = false;
        listenBtn.disabled = false;
        listenBtn.innerText = "Nasłuchuj komendy";
        speechOutput.scrollTop = speechOutput.scrollHeight;
    }
    });
}


// --- WYBÓR KAMERY ---
const cameraSelectFront = document.getElementById('camera-select-front');
const cameraSelectSide = document.getElementById('camera-select-side');

async function enumerateCameras() {
  try {
    // 1. Poproś o permissje (wybudzi uśpione kamery na niektórych systemach)
    // No więc ten kod generalnie zwieszał cv2 próbujące dostać się do kamery urządzenia (chyba?)
//    try {
//      await navigator.mediaDevices.getUserMedia({
//        video: { width: 1, height: 1 },
//        audio: false
//      }).then(stream => {
//        // Zamknij stream - był tylko do uaktywnienia kamer
//        stream.getTracks().forEach(track => track.stop());
//      });
//    } catch (e) {
//      // Ignoruj błędy permissji, spróbuj mimo to
//    }

    // 2. Wylicz urządzenia
    const devices = await navigator.mediaDevices.enumerateDevices();
    const videoDevices = devices.filter(device => device.kind === 'videoinput');

    console.log(`[Cameras] Znaleziono ${videoDevices.length} kamer:`);
    videoDevices.forEach((d, i) => {
      console.log(`  ${i + 1}. ${d.label || `Kamera ${i + 1}`} (${d.deviceId})`);
    });

    // 3. Aktualizuj oba selekty
    [cameraSelectFront, cameraSelectSide].forEach(select => {
      if (!select) return;
      
      const currentValue = select.value;
      select.innerHTML = '<option value="">-- Domyślna --</option>';

      if (videoDevices.length === 0) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'Brak dostępnych kamer';
        option.disabled = true;
        select.appendChild(option);
        return;
      }

      videoDevices.forEach((device, index) => {
        const option = document.createElement('option');
        // OpenCV po stronie Pythona wybiera kamerę po indeksie (0,1,2...).
        // Dlatego w config wysyłamy indeks, a nie browserowe deviceId (string).
        option.value = String(index);
        option.textContent = device.label || `Kamera ${index + 1}`;
        option.dataset.deviceId = device.deviceId;
        select.appendChild(option);
      });

      // Przywróć poprzednią wartość jeśli istnieje
      if (currentValue && videoDevices[Number(currentValue)]) {
        select.value = currentValue;
      }
    });

  } catch (error) {
    console.error('❌ Błąd przy pobieraniu listy kamer:', error);
    [cameraSelectFront, cameraSelectSide].forEach(select => {
      if (select) {
        select.innerHTML = '<option value="">Błąd dostępu do kamer</option>';
      }
    });
  }
}


// Audio monitoring for debugging
let audioContext = null;
let analyser = null;
let microphone = null;
let dataArray = null;
let animationFrame = null;
let isMonitoring = false;
let selectedDeviceId = null;

const startAudioDebugBtn = document.getElementById('start-audio-debug-btn');
const stopAudioDebugBtn = document.getElementById('stop-audio-debug-btn');
const micSelect = document.getElementById('mic-select');
const audioLevelBar = document.getElementById('audio-level-bar');
const audioLevelText = document.getElementById('audio-level-text');
const audioDebugInfo = document.getElementById('audio-debug-info');

// Enumerate available microphones
async function enumerateMicrophones() {
  if(!micSelect) return;
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const microphones = devices.filter(device => device.kind === 'audioinput');

    micSelect.innerHTML = '<option value="">Domyślny</option>';
    microphones.forEach(mic => {
      const option = document.createElement('option');
      option.value = mic.deviceId;
      option.textContent = mic.label || `Mikrofon ${mic.deviceId.slice(0, 8)}`;
      micSelect.appendChild(option);
    });

    console.log('[Audio Debug] Available microphones:', microphones.length);
  } catch (error) {
    console.error('[Audio Debug] Error enumerating microphones:', error);
    if(audioDebugInfo) audioDebugInfo.textContent = 'Błąd enumeracji mikrofonów';
  }
}

// Handle microphone selection change
if(micSelect) {
    micSelect.addEventListener('change', (e) => {
    selectedDeviceId = e.target.value || null;
    console.log('[Audio Debug] Selected microphone:', selectedDeviceId);
    });
}

async function startAudioMonitoring() {
  try {
    // Request microphone access with specific device if selected
    const constraints = {
      audio: {
        deviceId: selectedDeviceId ? { exact: selectedDeviceId } : undefined,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
        sampleRate: 44100,
        channelCount: 1
      }
    };

    const stream = await navigator.mediaDevices.getUserMedia(constraints);

    // Create audio context
    audioContext = new (window.AudioContext || window.webkitAudioContext)();

    // Resume audio context if suspended (required by modern browsers)
    if (audioContext.state === 'suspended') {
      await audioContext.resume();
    }

    analyser = audioContext.createAnalyser();
    microphone = audioContext.createMediaStreamSource(stream);

    // Configure analyser for better sensitivity
    analyser.fftSize = 512; // Increased for better frequency resolution
    analyser.smoothingTimeConstant = 0.1; // Reduced for more responsive updates
    analyser.minDecibels = -90;
    analyser.maxDecibels = -10;

    const bufferLength = analyser.frequencyBinCount;
    dataArray = new Uint8Array(bufferLength);

    // Connect microphone to analyser
    microphone.connect(analyser);

    isMonitoring = true;
    updateAudioLevel();

    if(micSelect && audioDebugInfo) {
        const selectedMicName = micSelect.options[micSelect.selectedIndex].textContent;
        audioDebugInfo.textContent = `Monitorowanie audio aktywne (FFT: ${analyser.fftSize}, Context: ${audioContext.state}, Mic: ${selectedMicName})`;
    }
    console.log('[Audio Debug] Started monitoring, context state:', audioContext.state);

  } catch (error) {
    console.error('[Audio Debug] Error starting monitoring:', error);
    if(audioDebugInfo) {
        audioDebugInfo.textContent = `Błąd: ${error.message}`;

        // Additional error information
        if (error.name === 'NotAllowedError') {
        audioDebugInfo.textContent += ' - Uprawnienia do mikrofonu zostały odrzucone';
        } else if (error.name === 'NotFoundError') {
        audioDebugInfo.textContent += ' - Mikrofon nie został znaleziony';
        } else if (error.name === 'NotReadableError') {
        audioDebugInfo.textContent += ' - Mikrofon jest już używany przez inną aplikację';
        } else if (error.name === 'OverconstrainedError') {
        audioDebugInfo.textContent += ' - Wybrany mikrofon nie jest dostępny';
        }
    }
  }
}

function stopAudioMonitoring() {
  if (animationFrame) {
    cancelAnimationFrame(animationFrame);
    animationFrame = null;
  }

  if (microphone) {
    microphone.disconnect();
    microphone = null;
  }

  if (audioContext && audioContext.state !== 'closed') {
    audioContext.close();
    audioContext = null;
  }

  analyser = null;
  dataArray = null;
  isMonitoring = false;

  if(audioLevelBar && audioLevelText && audioDebugInfo) {
      audioLevelBar.style.width = '0%';
      audioLevelText.textContent = 'Poziom: 0%';
      audioDebugInfo.textContent = 'Monitorowanie zatrzymane';
  }
  console.log('[Audio Debug] Stopped monitoring');
}

function updateAudioLevel() {
  if (!isMonitoring || !analyser || !dataArray) {
    return;
  }

  // Try different methods to get audio data
  analyser.getByteFrequencyData(dataArray);

  // Calculate RMS from frequency data
  let sum = 0;
  let validSamples = 0;

  // Focus on lower frequencies (voice range: ~85-255 Hz)
  const voiceStart = Math.floor(dataArray.length * 0.1); // ~85 Hz
  const voiceEnd = Math.floor(dataArray.length * 0.5);   // ~2000 Hz

  for (let i = voiceStart; i < voiceEnd; i++) {
    const value = dataArray[i] / 255.0; // Normalize to 0-1
    sum += value * value;
    validSamples++;
  }

  const rms = validSamples > 0 ? Math.sqrt(sum / validSamples) : 0;
  const level = Math.min(100, rms * 1000); // Amplify for visibility

  // Alternative: use getByteTimeDomainData for waveform
  const timeDataArray = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(timeDataArray);

  let timeSum = 0;
  for (let i = 0; i < timeDataArray.length; i++) {
    const sample = (timeDataArray[i] - 128) / 128.0; // Convert to -1 to 1
    timeSum += sample * sample;
  }
  const timeRms = Math.sqrt(timeSum / timeDataArray.length);
  const timeLevel = Math.min(100, timeRms * 500); // Different scaling

  // Use the higher of the two measurements
  const finalLevel = Math.max(level, timeLevel);

  if(audioLevelBar && audioLevelText) {
      // Update UI
      audioLevelBar.style.width = `${finalLevel}%`;
      audioLevelText.textContent = `Poziom: ${finalLevel.toFixed(1)}% (RMS: ${rms.toFixed(3)}, Time: ${timeRms.toFixed(3)})`;

      // Color coding based on level
      if (finalLevel < 5) {
        audioLevelBar.style.background = '#6c757d'; // Gray for very low
      } else if (finalLevel < 20) {
        audioLevelBar.style.background = '#28a745'; // Green for normal
      } else if (finalLevel < 50) {
        audioLevelBar.style.background = '#ffc107'; // Yellow for high
      } else {
        audioLevelBar.style.background = '#dc3545'; // Red for very high
      }
  }

  animationFrame = requestAnimationFrame(updateAudioLevel);
}

if(startAudioDebugBtn && stopAudioDebugBtn) {
    startAudioDebugBtn.addEventListener('click', () => {
    startAudioMonitoring();
    startAudioDebugBtn.style.display = 'none';
    stopAudioDebugBtn.style.display = 'inline-block';
    });

    stopAudioDebugBtn.addEventListener('click', () => {
    stopAudioMonitoring();
    startAudioDebugBtn.style.display = 'inline-block';
    stopAudioDebugBtn.style.display = 'none';
    });
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
  stopAudioMonitoring();
});

//obsługa przycisku ustawień
const saveSettingsBtn = document.getElementById('save-settings-btn');
const languageSelect = document.getElementById('language-select');
const volumeSlider = document.getElementById('volume-slider');
const volumeDisplay = document.getElementById('volume-display');
const speechRateSlider = document.getElementById('speech-rate-slider');
const speechRateDisplay = document.getElementById('speech-rate-display');

// Aktualizacja wyświetlania głośności
if(volumeSlider && volumeDisplay) {
    volumeSlider.addEventListener('input', () => {
    volumeDisplay.textContent = volumeSlider.value + '%';
    });
}

// Aktualizacja wyświetlania szybkości mówienia
if(speechRateSlider && speechRateDisplay) {
    speechRateSlider.addEventListener('input', () => {
    speechRateDisplay.textContent = speechRateSlider.value;
    });
}

// Zapisywanie ustawień
if(saveSettingsBtn) {
    saveSettingsBtn.addEventListener('click', async () => {
    const settings = {
        language: languageSelect ? languageSelect.value : 'pl-PL',
        volume: volumeSlider ? parseFloat(volumeSlider.value) / 100 : 1, // Konwertuj na 0-1 dla Python
        speech_rate: speechRateSlider ? parseInt(speechRateSlider.value) : 150
    };

    try {
        const response = await fetchWithTimeout(`${audioServiceUrl}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
        }, 10000);

        if (!response.ok) {
        const body = await response.text();
        throw new Error(`Błąd serwera: ${response.status} ${body}`);
        }

        const data = await response.json();
        if (data.status === 'success') {
        if(speechOutput) speechOutput.value += `\n✓ Ustawienia zapisane pomyślnie`;
        // Zapisz również lokalnie
        saveSettings({
            language: settings.language,
            volume: volumeSlider ? parseInt(volumeSlider.value) : 100, // Zachowaj jako procent dla UI
            speechRate: settings.speech_rate
        });
        console.log('Ustawienia zapisane:', settings);
        } else {
        if(speechOutput) speechOutput.value += `\n✗ Błąd zapisywania ustawień: ${data.message}`;
        }
    } catch (error) {
        if(speechOutput) speechOutput.value += `\n[Błąd zapisywania ustawień]: ${error.message}`;
        console.error("Błąd /settings:", error);
    }

    if(speechOutput) speechOutput.scrollTop = speechOutput.scrollHeight;
    });
}

// Inicjalizacja ustawień przy starcie aplikacji
document.addEventListener('DOMContentLoaded', async () => {
  // Zainicjuj listy urządzeń
  enumerateMicrophones();
  enumerateCameras();

  // Inicjalizuj Config Service (zbieranie i wysyłanie konfiguracji)
  if (typeof initializeConfigService === 'function') {
    initializeConfigService();
  }

  // Najpierw załaduj ustawienia lokalne jako fallback
  const localSettings = loadSettings();
  applySettingsToUI(localSettings);

  // Następnie spróbuj załadować ustawienia z serwera
  try {
    const response = await fetchWithTimeout(`${audioServiceUrl}/settings`, {}, 5000);
    if (response.ok) {
      const data = await response.json();
      if (data.status === 'success' && data.settings) {
        // Zaktualizuj ustawienia lokalne ustawieniami z serwera
        const serverSettings = {
          language: data.settings.language,
          volume: Math.round(data.settings.volume * 100), // Konwertuj na procenty
          speechRate: data.settings.speech_rate
        };
        saveSettings(serverSettings);
        applySettingsToUI(serverSettings);
        console.log('Ustawienia załadowane z serwera:', serverSettings);
        if(speechOutput) speechOutput.value += `\n✓ Ustawienia załadowane z serwera`;
      }
    }
  } catch (error) {
    console.log('Nie można załadować ustawień z serwera, używam lokalnych:', error.message);
    if(speechOutput) speechOutput.value += `\n✓ Ustawienia załadowane lokalnie`;
  }

  if(speechOutput) speechOutput.scrollTop = speechOutput.scrollHeight;
});

// Nasłuchuj zmian urządzeń multimedialnych (np. podłączenie/odłączenie kamery/mikrofonu)
navigator.mediaDevices.addEventListener('devicechange', () => {
    enumerateMicrophones();
    enumerateCameras();
});