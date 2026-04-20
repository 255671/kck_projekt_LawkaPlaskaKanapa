const { ipcRenderer } = require('electron');

ipcRenderer.on('mediapipe-data', (event, data) => {
  console.log('Received from Python:', data);

  if (data.image) {
    document.getElementById('camera').src = 'data:image/jpeg;base64,' + data.image;
  } else {
    document.getElementById('output').innerText = JSON.stringify(data);
  }
});


async function sendToAudio() {
  await fetch('http://localhost:5000/speak', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: 'Hello from Electron' })
  });
}