document.addEventListener('DOMContentLoaded', () => {

    const toggleCameraBtn = document.getElementById('toggle-camera-btn');
    const cameraElement = document.getElementById('camera');
    const toggleTextSpan = toggleCameraBtn.querySelector('span');

    toggleCameraBtn.addEventListener('click', () => {
      if (cameraElement.classList.contains('hidden')) {
        cameraElement.classList.remove('hidden');
        toggleTextSpan.textContent = 'Ukryj kamerę';
        toggleCameraBtn.classList.replace('btn-primary', 'btn-danger');
      } else {
        cameraElement.classList.add('hidden');
        toggleTextSpan.textContent = 'Pokaż kamerę';
        toggleCameraBtn.classList.replace('btn-danger', 'btn-primary');
      }
    });

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