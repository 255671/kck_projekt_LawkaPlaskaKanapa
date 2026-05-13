document.addEventListener('DOMContentLoaded', () => {

    // --- SYSTEM ZAKŁADEK (TABS) ---
    const navButtons = document.querySelectorAll('.nav-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    navButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            // Usuń aktywną klasę ze wszystkich
            navButtons.forEach(b => b.classList.remove('active'));
            tabContents.forEach(tc => tc.classList.remove('active'));

            // Dodaj aktywną klasę do klikniętego
            btn.classList.add('active');
            const targetId = btn.getAttribute('data-target');
            document.getElementById(targetId).classList.add('active');
        });
    });


    // --- TOGGLE KAMERY ---
    const toggleCameraBtn = document.getElementById('toggle-camera-btn');
    const cameraElement = document.getElementById('camera');

    if (toggleCameraBtn && cameraElement) {
        const toggleTextSpan = toggleCameraBtn.querySelector('span');

        toggleCameraBtn.addEventListener('click', () => {
        if (cameraElement.classList.contains('hidden')) {
            cameraElement.classList.remove('hidden');
            toggleTextSpan.textContent = 'Ukryj kamerę';
            // Zmiana stylu na aktywny
            toggleCameraBtn.style.backgroundColor = 'transparent';
            toggleCameraBtn.style.color = 'var(--c1)';
            toggleCameraBtn.style.borderColor = 'var(--c4)';
        } else {
            cameraElement.classList.add('hidden');
            toggleTextSpan.textContent = 'Pokaż kamerę';
            // Powrót do pierwotnego stylu
            toggleCameraBtn.style.backgroundColor = 'var(--c3)';
            toggleCameraBtn.style.color = 'var(--text-dark)';
            toggleCameraBtn.style.borderColor = 'var(--c3)';
        }
        });
    }


    // --- AKTUALIZACJA SUWAKÓW ---
    const volumeSlider = document.getElementById('volume-slider');
    const volumeDisplay = document.getElementById('volume-display');

    if(volumeSlider && volumeDisplay) {
        volumeSlider.addEventListener('input', (e) => {
            volumeDisplay.textContent = `${e.target.value}%`;
        });
    }

    const speechRateSlider = document.getElementById('speech-rate-slider');
    const speechRateDisplay = document.getElementById('speech-rate-display');

    if(speechRateSlider && speechRateDisplay) {
        speechRateSlider.addEventListener('input', (e) => {
            speechRateDisplay.textContent = e.target.value;
        });
    }


    // --- PRZYCISKI DEBUGOWANIA AUDIO ---
    const startAudioBtn = document.getElementById('start-audio-debug-btn');
    const stopAudioBtn = document.getElementById('stop-audio-debug-btn');

    if(startAudioBtn && stopAudioBtn) {
        startAudioBtn.addEventListener('click', () => {
            startAudioBtn.classList.add('hidden');
            stopAudioBtn.classList.remove('hidden');
        });

        stopAudioBtn.addEventListener('click', () => {
            stopAudioBtn.classList.add('hidden');
            startAudioBtn.classList.remove('hidden');
        });
    }
});