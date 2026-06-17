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
  theme: 'light',
  language: 'pl-PL',
  volume: 100,
  speechRate: 1.0
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
  const theme = settings.theme || 'light';
  document.documentElement.setAttribute('data-theme', theme);
  const themeSelect = document.getElementById('theme-select');
  if (themeSelect) themeSelect.value = theme;

  document.getElementById('language-select').value = settings.language;
  document.getElementById('volume-slider').value = settings.volume;
  document.getElementById('volume-display').textContent = settings.volume + '%';
  document.getElementById('speech-rate-slider').value = settings.speechRate;
  document.getElementById('speech-rate-display').textContent = settings.speechRate + 'x';
  
  if (typeof loadHistory === 'function') loadHistory();
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

let previousRepCount = 0;
let previousDisplayRepCount = 0;
let lastPostureSpokenAtMs = 0;

let trainingMode = false;
let trainingState = {
   targetLeg: 'right', // 'right' or 'left'
   repsDone: 0,
   targetReps: 10,
   startTime: null,
   timerInterval: null,
   errors: 0,
   repDetails: []
};
let errorCountedThisRep = false;

async function speakMessage(text) {
  try {
    await fetchWithTimeout(`${audioServiceUrl}/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text })
    }, 5000);
  } catch (e) {
    console.log("Mowa niedostępna:", e);
  }
}

let countdownInterval = null;

async function startTraining() {
    const countdownInput = document.getElementById('countdown-input');
    let countdownVal = countdownInput ? parseInt(countdownInput.value) : 5;
    
    document.querySelector('.dashboard-container').classList.add('training-active');
    
    const globalStartBtn = document.getElementById('global-start-btn');
    if (globalStartBtn) globalStartBtn.style.display = 'none';
    
    // Pokaż główne elementy kontrolne (HUD timera) od razu, by układ nie skakał
    document.getElementById('hud-training-info').classList.remove('hidden');
    document.getElementById('hud-training-controls').classList.remove('hidden');
    document.getElementById('training-leg-label').textContent = 'Przygotowanie...';
    
    const formatTime = (secs) => {
        const m = String(Math.floor(secs / 60)).padStart(2, '0');
        const s = String(secs % 60).padStart(2, '0');
        return `${m}:${s}`;
    };
    
    document.getElementById('training-timer').textContent = formatTime(countdownVal);
    
    if (countdownVal > 0) {
        // Zaczekaj z odliczaniem aż asystent skończy mówić
        await speakMessage(`Ustaw się. Trening zacznie się za ${countdownVal} sekund.`);
        
        if (countdownInterval) clearInterval(countdownInterval);
        countdownInterval = setInterval(() => {
            countdownVal--;
            document.getElementById('training-timer').textContent = formatTime(countdownVal);
            
            if (countdownVal <= 0) {
                clearInterval(countdownInterval);
                beginActualTraining();
            }
        }, 1000);
    } else {
        beginActualTraining();
    }
}

async function beginActualTraining() {
    trainingMode = true;
    const repsInput = document.getElementById('repetitions-input');
    trainingState.targetReps = repsInput ? parseInt(repsInput.value) : 10;
    trainingState.repsDone = 0;
    trainingState.errors = 0;
    trainingState.targetLeg = 'right';
    trainingState.startTime = Date.now();
    trainingState.repDetails = [];
    trainingState.currentRepErrorType = "";
    errorCountedThisRep = false;
    previousRepCount = 0;

    document.getElementById('training-leg-label').textContent = 'Prawa noga';
    document.getElementById('hud-reps').innerHTML = `0 <span class="hud-target" id="hud-target-val">/ ${trainingState.targetReps}</span>`;
    
    const errEl = document.getElementById('hud-errors');
    if(errEl) errEl.textContent = '0';

    if (trainingState.timerInterval) clearInterval(trainingState.timerInterval);
    trainingState.timerInterval = setInterval(updateTrainingTimer, 1000);
    
    speakMessage("Start! Prawa noga.");
}

function updateTrainingTimer() {
    const now = Date.now();
    const diff = Math.floor((now - trainingState.startTime) / 1000);
    const mins = String(Math.floor(diff / 60)).padStart(2, '0');
    const secs = String(diff % 60).padStart(2, '0');
    document.getElementById('training-timer').textContent = `${mins}:${secs}`;
}

function stopTraining(completed = false) {
    trainingMode = false;
    if (countdownInterval) clearInterval(countdownInterval);
    if (trainingState.timerInterval) clearInterval(trainingState.timerInterval);
    
    document.querySelector('.dashboard-container').classList.remove('training-active');
    
    const globalStartBtn = document.getElementById('global-start-btn');
    if (globalStartBtn) globalStartBtn.style.display = 'flex';
    
    document.getElementById('hud-training-info').classList.add('hidden');
    document.getElementById('hud-training-controls').classList.add('hidden');
    
    if (completed) {
        const timeStr = document.getElementById('training-timer').textContent;
        const totalReps = trainingState.targetReps * 2; // Lewa + Prawa
        const totalErrors = trainingState.errors;
        
        document.getElementById('summary-time').textContent = timeStr;
        document.getElementById('summary-reps').textContent = `${totalReps} łącznie`;
        document.getElementById('summary-errors').textContent = totalErrors;
        
        let rating = "Idealnie!";
        let ratingColor = "var(--c3)";
        if (totalErrors > 0 && totalErrors <= 3) {
            rating = "Dobrze";
            ratingColor = "var(--c2)";
        } else if (totalErrors > 3) {
            rating = "Do poprawy";
            ratingColor = "#ff4444";
        }
        
        const ratingEl = document.getElementById('summary-rating');
        if (ratingEl) {
            ratingEl.textContent = rating;
            ratingEl.style.color = ratingColor;
        }
        
        document.getElementById('summary-overlay').classList.remove('hidden');
        
        // Zapis do JSON DB
        const workoutData = {
            date: new Date().toISOString(),
            time: timeStr,
            reps: totalReps,
            errors: totalErrors,
            repDetails: [...(trainingState.repDetails || [])]
        };
        saveWorkout(workoutData);
        
        speakMessage(`Trening zakończony pomyślnie. Czas: ${timeStr}. Zarejestrowane błędy: ${totalErrors}.`);
    } else {
        speakMessage("Trening anulowany.");
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('start-training-btn')?.addEventListener('click', startTraining);
    document.getElementById('cancel-training-btn')?.addEventListener('click', () => stopTraining(false));
    
    // Obsługa globalnego przycisku START
    const globalStartBtn = document.getElementById('global-start-btn');
    if (globalStartBtn) {
        globalStartBtn.addEventListener('click', () => {
            // Przełączenie na zakładkę Trening
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            const targetTab = document.getElementById('tab-training');
            const targetBtn = document.querySelector('[data-tab="tab-training"]');
            if (targetTab && targetBtn) {
                targetTab.classList.add('active');
                targetBtn.classList.add('active');
            }
            startTraining();
        });
        globalStartBtn.addEventListener('mouseenter', () => globalStartBtn.style.transform = 'scale(1.1)');
        globalStartBtn.addEventListener('mouseleave', () => globalStartBtn.style.transform = 'scale(1)');
    }
    
    // Przycisk zamykający okienko podsumowania
    document.getElementById('summary-close-btn')?.addEventListener('click', () => {
        document.getElementById('summary-overlay').classList.add('hidden');
    });
    
    // Obsługa własnego okienka do usuwania
    document.getElementById('delete-cancel-btn')?.addEventListener('click', () => {
        document.getElementById('delete-confirm-overlay').classList.add('hidden');
        workoutToDeleteIndex = null;
    });

    document.getElementById('delete-confirm-btn')?.addEventListener('click', () => {
        if (workoutToDeleteIndex !== null) {
            deleteWorkout(workoutToDeleteIndex);
            workoutToDeleteIndex = null;
        }
        document.getElementById('delete-confirm-overlay').classList.add('hidden');
    });
    
    document.getElementById('details-close-btn')?.addEventListener('click', () => {
        document.getElementById('workout-details-overlay').classList.add('hidden');
    });
    
    updateStatsUI();
});

// =========================================================
// DATABASE & STATS
// =========================================================
function getWorkouts() {
    const data = localStorage.getItem('workoutsDB');
    return data ? JSON.parse(data) : [];
}

function saveWorkout(workout) {
    const data = getWorkouts();
    data.push(workout);
    localStorage.setItem('workoutsDB', JSON.stringify(data));
    updateStatsUI();
}

function deleteWorkout(index) {
    const data = getWorkouts();
    if (index >= 0 && index < data.length) {
        data.splice(index, 1);
        localStorage.setItem('workoutsDB', JSON.stringify(data));
        updateStatsUI();
    }
}

let accuracyChartInstance = null;
let workoutToDeleteIndex = null;

function updateStatsUI() {
    const data = getWorkouts();
    
    let totalReps = 0;
    let totalErrors = 0;
    data.forEach(w => {
        totalReps += w.reps || 0;
        totalErrors += w.errors || 0;
    });
    
    const workoutsEl = document.getElementById('stats-total-workouts');
    if (workoutsEl) workoutsEl.textContent = data.length;
    
    const repsEl = document.getElementById('stats-total-reps');
    if (repsEl) repsEl.textContent = totalReps;
    
    const errorsEl = document.getElementById('stats-total-errors');
    if (errorsEl) errorsEl.textContent = totalErrors;
    
    const accEl = document.getElementById('stats-accuracy');
    if (accEl) {
        if (totalReps === 0) {
            accEl.textContent = '--%';
        } else {
            const accuracy = Math.max(0, 100 - ((totalErrors / totalReps) * 100));
            accEl.textContent = accuracy.toFixed(1) + '%';
        }
    }
    
    const historyList = document.getElementById('history-list');
    if (historyList) {
        historyList.innerHTML = '';
        if (data.length === 0) {
            historyList.innerHTML = '<div style="color: #666; text-align: center; margin-top: 20px;">Brak zapisanych treningów.</div>';
        } else {
            const reversed = [...data].reverse();
            reversed.forEach((w, reversedIdx) => {
                const originalIdx = data.length - 1 - reversedIdx;
                const item = document.createElement('div');
                item.id = `history-item-${originalIdx}`;
                item.style.background = 'rgba(255,255,255,0.05)';
                item.style.padding = '12px';
                item.style.borderRadius = '6px';
                item.style.display = 'flex';
                item.style.justifyContent = 'space-between';
                item.style.transition = 'all 0.3s ease';
                item.style.border = '1px solid transparent';
                
                const dateObj = new Date(w.date);
                const dateStr = dateObj.toLocaleDateString() + ' ' + dateObj.toLocaleTimeString();
                
                item.innerHTML = `
                  <div style="flex: 1;">
                     <div style="font-weight: bold; color: var(--c3);">${dateStr}</div>
                     <div style="font-size: 12px; color: var(--c1);">Czas trwania: ${w.time}</div>
                  </div>
                  <div style="text-align: right; display: flex; align-items: center; gap: 15px;">
                     <div>
                       <div style="font-weight: bold; color: var(--text-main);">${w.reps} powtórzeń</div>
                       <div style="font-size: 12px; color: #ff4444;">${w.errors} błędów</div>
                     </div>
                     <button class="delete-workout-btn" title="Usuń trening" style="background: none; border: none; color: #ff4444; cursor: pointer; padding: 5px; opacity: 0.7; transition: opacity 0.2s;">
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
                     </button>
                  </div>
                `;
                
                // Zdarzenie usuwania
                const delBtn = item.querySelector('.delete-workout-btn');
                delBtn.addEventListener('mouseenter', () => delBtn.style.opacity = '1');
                delBtn.addEventListener('mouseleave', () => delBtn.style.opacity = '0.7');
                delBtn.addEventListener('click', (e) => {
                    e.stopPropagation(); // nie wyzwalaj zdarzeń dla nadrzędnych elementów
                    workoutToDeleteIndex = originalIdx;
                    document.getElementById('delete-confirm-overlay').classList.remove('hidden');
                });
                
                // Zdarzenie podglądu
                item.style.cursor = 'pointer';
                item.addEventListener('click', () => {
                    showWorkoutDetails(w);
                });
                
                historyList.appendChild(item);
            });
        }
    }
    
    // Generowanie Wykresu
    const ctx = document.getElementById('accuracyChart');
    if (ctx && window.Chart) {
        const labels = data.map((w, idx) => `Tr. ${idx+1}`);
        const chartData = data.map(w => {
            if (!w.reps) return 0;
            return Math.max(0, 100 - (w.errors / w.reps * 100)).toFixed(1);
        });

        if (accuracyChartInstance) {
            accuracyChartInstance.destroy();
        }
        
        const rootStyles = getComputedStyle(document.documentElement);
        const chartColor = rootStyles.getPropertyValue('--chart-color').trim();
        const chartBg = rootStyles.getPropertyValue('--chart-bg').trim();

        accuracyChartInstance = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Poprawność (%)',
                    data: chartData,
                    borderColor: chartColor,
                    backgroundColor: chartBg,
                    borderWidth: 2,
                    pointBackgroundColor: chartColor,
                    pointRadius: 5,
                    pointHoverRadius: 8,
                    fill: true,
                    tension: 0.3
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        grid: { color: 'rgba(255, 255, 255, 0.1)' },
                        ticks: { color: '#ccc' }
                    },
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.1)' },
                        ticks: { color: '#ccc' }
                    }
                },
                plugins: {
                    legend: { display: false }
                },
                onClick: (e, elements) => {
                    if (elements.length > 0) {
                        const dataIndex = elements[0].index; // maps to originalIdx
                        // Reset all highlights
                        const listItems = document.querySelectorAll('[id^="history-item-"]');
                        listItems.forEach(el => {
                            el.style.background = 'rgba(255,255,255,0.05)';
                            el.style.border = '1px solid transparent';
                        });
                        
                        const targetItem = document.getElementById(`history-item-${dataIndex}`);
                        if (targetItem) {
                            targetItem.style.background = chartBg;
                            targetItem.style.border = `1px solid ${chartColor}`;
                            targetItem.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                        }
                    }
                }
            }
        });
    }
}

function showWorkoutDetails(workout) {
    const overlay = document.getElementById('workout-details-overlay');
    const headerInfo = document.getElementById('details-header-info');
    const repsList = document.getElementById('details-reps-list');
    
    if (!overlay || !headerInfo || !repsList) return;
    
    const dateObj = new Date(workout.date);
    headerInfo.textContent = `Data: ${dateObj.toLocaleDateString()} ${dateObj.toLocaleTimeString()} | Czas: ${workout.time} | Błędy: ${workout.errors}/${workout.reps}`;
    
    repsList.innerHTML = '';
    
    if (!workout.repDetails || workout.repDetails.length === 0) {
        repsList.innerHTML = '<div style="color: var(--c1); text-align: center; padding: 20px;">Brak danych szczegółowych z tego treningu.</div>';
    } else {
        workout.repDetails.forEach(rep => {
            const row = document.createElement('div');
            row.style.display = 'flex';
            row.style.justifyContent = 'space-between';
            row.style.padding = '10px 15px';
            row.style.borderRadius = '4px';
            
            const legName = rep.leg === 'right' ? 'Prawa noga' : 'Lewa noga';
            const statusColor = rep.hasError ? '#ff4444' : '#2ecc71';
            const statusText = rep.hasError ? (rep.errorType || 'Błąd postawy') : 'Idealnie';
            
            row.style.background = rep.hasError ? 'rgba(255, 68, 68, 0.1)' : 'rgba(46, 204, 113, 0.1)';
            row.style.borderLeft = `4px solid ${statusColor}`;
            
            row.innerHTML = `
              <div style="color: var(--text-main);">${legName} - Powtórzenie ${rep.repNumber}</div>
              <div style="color: ${statusColor}; font-weight: bold;">${statusText}</div>
            `;
            
            repsList.appendChild(row);
        });
    }
    
    overlay.classList.remove('hidden');
}

function updateExerciseUI(exercise) {
  if (!exercise) return;

  const repCount = typeof exercise.repCount === 'number' ? exercise.repCount : 0;
  const phase = exercise.phase || 'NOT_READY';
  const kneeAngle = exercise.metrics && typeof exercise.metrics.kneeAngle === 'number'
    ? exercise.metrics.kneeAngle
    : null;

  // New HUD Elements
  const hudRepsEl = document.getElementById('hud-reps');
  const hudAngleEl = document.getElementById('hud-angle');
  const repetitionsInput = document.getElementById('repetitions-input');

  // Update HUD
  if (hudAngleEl) {
    hudAngleEl.textContent = kneeAngle !== null ? `${kneeAngle}°` : '--°';
  }

  // --- LOGIKA PĘTLI TRENINGU ---
  let displayRepCount = repCount;
  const target = repetitionsInput ? repetitionsInput.value : '10';

  if (trainingMode) {
      if (phase === 'READY') {
          errorCountedThisRep = false;
          trainingState.currentRepErrorType = "";
      }

      // Alert o postawie w każdej chwili podczas treningu
      if (exercise.metrics && exercise.metrics.badPosture) {
          if (['DESCENDING', 'BOTTOM', 'ASCENDING'].includes(phase) && !errorCountedThisRep) {
              errorCountedThisRep = true;
              trainingState.currentRepErrorType = exercise.metrics.postureErrorType || "Błąd postawy";
              trainingState.errors++;
              const errEl = document.getElementById('hud-errors');
              if(errEl) errEl.textContent = trainingState.errors;
         }

         const now = Date.now();
         if (now - lastPostureSpokenAtMs > 8000) {
             lastPostureSpokenAtMs = now;
             speakMessage("Wyprostuj plecy.");
         }
     }

     if (repCount > previousRepCount) {
         if (exercise.lastLeg === trainingState.targetLeg) {
             trainingState.repsDone++;
             
             trainingState.repDetails.push({
                  leg: trainingState.targetLeg,
                  repNumber: trainingState.repsDone,
                  hasError: errorCountedThisRep,
                  errorType: trainingState.currentRepErrorType
             });
             
             if (trainingState.repsDone >= trainingState.targetReps) {
                 if (trainingState.targetLeg === 'right') {
                     // Zmiana na lewą nogę
                     trainingState.targetLeg = 'left';
                     trainingState.repsDone = 0;
                     document.getElementById('training-leg-label').textContent = 'Lewa noga';
                     speakMessage("Zmień nogę. Teraz lewa noga.");
                 } else {
                     // Koniec treningu
                     stopTraining(true);
                     return;
                 }
             }
         } else {
             console.log(`Zignorowano powtórzenie. Zrobiono: ${exercise.lastLeg}, a wymagano: ${trainingState.targetLeg}`);
             speakMessage("Zła noga.");
         }
     }
     displayRepCount = trainingState.repsDone;
  }

  if (hudRepsEl) {
    // Rep bump animation
    if (displayRepCount > previousDisplayRepCount) {
      hudRepsEl.innerHTML = `${displayRepCount} <span class="hud-target" id="hud-target-val">/ ${target}</span>`;
      hudRepsEl.classList.remove('rep-bump');
      void hudRepsEl.offsetWidth; // trigger reflow
      hudRepsEl.classList.add('rep-bump');
      
      // Remove animation class after it finishes
      setTimeout(() => {
        if(hudRepsEl) hudRepsEl.classList.remove('rep-bump');
      }, 300);
      
    } else if (displayRepCount !== previousDisplayRepCount || !hudRepsEl.innerHTML.includes(target)) {
      hudRepsEl.innerHTML = `${displayRepCount} <span class="hud-target" id="hud-target-val">/ ${target}</span>`;
    }
    previousDisplayRepCount = displayRepCount;
  }
  previousRepCount = repCount;

  // Update Phase Tracker
  const allSteps = ['NOT_READY', 'READY', 'DESCENDING', 'BOTTOM', 'ASCENDING', 'TOP'];
  allSteps.forEach(step => {
    const stepEl = document.getElementById(`phase-${step}`);
    if (stepEl) {
      if (step === phase) {
        stepEl.classList.add('active');
      } else {
        stepEl.classList.remove('active');
      }
    }
  });

  // Update older stats (if they still exist)
  const statsRepCountEl = document.getElementById('stats-rep-count');
  const statsRepPhaseEl = document.getElementById('stats-rep-phase');
  const statsKneeAngleEl = document.getElementById('stats-knee-angle');
  const statsRepTargetEl = document.getElementById('stats-rep-target');
  
  if (statsRepCountEl) statsRepCountEl.textContent = String(repCount);
  if (statsRepPhaseEl) statsRepPhaseEl.textContent = phase;
  if (statsKneeAngleEl) statsKneeAngleEl.textContent = kneeAngle !== null ? String(kneeAngle) : '--';
  if (statsRepTargetEl && repetitionsInput) {
    statsRepTargetEl.textContent = repetitionsInput.value || '10';
  }
}

ipcRenderer.on('mediapipe-data', (event, data) => {
  if (data.exercise) {
    updateExerciseUI(data.exercise);
  }

  if (data.image || data.imageSide) {
    if (data.image) {
      document.getElementById('camera').src = 'data:image/jpeg;base64,' + data.image;
    }
    if (data.imageSide) {
      document.getElementById('camera-side').src = 'data:image/jpeg;base64,' + data.imageSide;
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
          const metricText = m
            ? ` angle=${m.kneeAngle} leg=${m.leg} src=${m.source || '?'} armed=${m.armed ? 'yes' : 'no'}`
            : ' brak metryk';
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
    if (output) {
      output.innerText += '\n' + JSON.stringify(data);
      output.scrollTop = output.scrollHeight;
    }
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

ipcRenderer.on('available-cameras', (event, cameras) => {
  console.log(`[Cameras] Znaleziono ${cameras.length} kamer z Pythona:`, cameras);
  
  [cameraSelectFront, cameraSelectSide].forEach(select => {
    if (!select) return;
    const currentValue = select.value;
    select.innerHTML = '<option value="">-- Domyślna --</option>';

    if (!cameras || cameras.length === 0) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'Brak dostępnych kamer';
      option.disabled = true;
      select.appendChild(option);
      return;
    }

    cameras.forEach(cam => {
      const option = document.createElement('option');
      option.value = String(cam.index);
      option.textContent = cam.name || `Kamera ${cam.index}`;
      select.appendChild(option);
    });

    // Przywróć poprzednią wartość jeśli istnieje
    if (currentValue) {
      select.value = currentValue;
    }
  });
});

async function enumerateCameras() {
  // Przeniesiono do Pythona w celu synchronizacji indeksów z OpenCV
}


// Audio monitoring for debugging
let audioContext = null;
let analyser = null;
// Ustawienia i opcje konfiguracyjne zostały zachowane, usunięto obsługę mikrofonu.

//obsługa przycisku ustawień
const saveSettingsBtn = document.getElementById('save-settings-btn');
const themeSelect = document.getElementById('theme-select');
const languageSelect = document.getElementById('language-select');
const volumeSlider = document.getElementById('volume-slider');
const volumeDisplay = document.getElementById('volume-display');
const speechRateSlider = document.getElementById('speech-rate-slider');
const speechRateDisplay = document.getElementById('speech-rate-display');

// Szybki podgląd motywu (bez zapisu)
if (themeSelect) {
    themeSelect.addEventListener('change', (e) => {
        document.documentElement.setAttribute('data-theme', e.target.value);
        if (typeof loadHistory === 'function') loadHistory();
    });
}

// Aktualizacja wyświetlania głośności
if(volumeSlider && volumeDisplay) {
    volumeSlider.addEventListener('input', () => {
    volumeDisplay.textContent = volumeSlider.value + '%';
    });
}

// Aktualizacja wyświetlania szybkości mówienia
if(speechRateSlider && speechRateDisplay) {
    speechRateSlider.addEventListener('input', () => {
    speechRateDisplay.textContent = speechRateSlider.value + 'x';
    });
}

// Zapisywanie ustawień
if(saveSettingsBtn) {
    saveSettingsBtn.addEventListener('click', async () => {
    const settings = {
        theme: themeSelect ? themeSelect.value : 'light',
        language: languageSelect ? languageSelect.value : 'pl-PL',
        volume: volumeSlider ? parseFloat(volumeSlider.value) / 100 : 1, // Konwertuj na 0-1 dla Python
        speech_rate: speechRateSlider ? Math.round(parseFloat(speechRateSlider.value) * 150) : 150
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
            theme: themeSelect ? themeSelect.value : 'light',
            language: settings.language,
            volume: volumeSlider ? parseInt(volumeSlider.value) : 100, // Zachowaj jako procent dla UI
            speechRate: speechRateSlider ? parseFloat(speechRateSlider.value) : 1.0
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

document.addEventListener('DOMContentLoaded', async () => {
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
          theme: localSettings.theme || 'light', // Z serwera nie przychodzi theme, więc używamy lokalnego
          language: data.settings.language,
          volume: Math.round(data.settings.volume * 100), // Konwertuj na procenty
          speechRate: data.settings.speech_rate ? parseFloat((data.settings.speech_rate / 150).toFixed(1)) : 1.0
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