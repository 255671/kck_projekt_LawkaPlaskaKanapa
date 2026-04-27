const { ipcRenderer } = require('electron');

ipcRenderer.on('mediapipe-data', (event, data) => {
  console.log('Received from Python:', data);

  if (data.image) {
    document.getElementById('camera').src = 'data:image/jpeg;base64,' + data.image;
  } else {
    document.getElementById('output').innerText = JSON.stringify(data);
  }
});

/*
async function sendToAudio() {
  await fetch('http://localhost:5000/speak', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: 'Hello from Electron' })
  });
}
*/

const speakBtn = document.getElementById('speak-btn');

//obsluga przycisku czytania (text to speech)
speakBtn.addEventListener('click', async () => {
  const textToSay = speechOutput.value;

  if (textToSay.trim() === "") {
    console.log("Pole tekstowe jest puste, nie ma czego czytać.");
    return; 
  }

  speakBtn.disabled = true;
  speakBtn.innerText = "Mówię...";

  try {
    //tekst do Pythona
    await fetch('http://localhost:5000/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: textToSay }) 
    });
    console.log("Wysłano tekst do przeczytania.");
  } catch (error) {
    console.error("Błąd połączenia z serwerem Flask:", error);
  } finally {
    speakBtn.disabled = false;
    speakBtn.innerText = "Przeczytaj tekst";
  }
});

const listenBtn = document.getElementById('listen-btn');
const speechOutput = document.getElementById('speech-output');



//obsluga klikniecia przycisku do nasluchiwania (speech to text)
listenBtn.addEventListener('click', async () => {
  speechOutput.scrollTop = speechOutput.scrollHeight; 
  listenBtn.disabled = true;
  listenBtn.innerText = "Słucham...";

  try {
    // zapytanie do serwera flask
    const response = await fetch('http://localhost:5000/listen');
    const data = await response.json();

    if (data.status === 'ok') {
      speechOutput.value += `\nTy: ${data.text}`;
    } else {
      speechOutput.value += `\n[Info]: ${data.message}`;
    }
  } catch (error) {
    speechOutput.value += `\n[Błąd połączenia]: Upewnij się, że audio_service.py działa.`;
    console.error(error);
  } finally {
    listenBtn.disabled = false;
    listenBtn.innerText = "Nasłuchuj komendy";
    speechOutput.scrollTop = speechOutput.scrollHeight;
  }
});