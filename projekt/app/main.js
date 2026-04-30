const { app, BrowserWindow } = require('electron');
const WebSocket = require('ws');
const { spawn } = require('child_process');
const path = require('path');

let mediapipeProcess;
let audioProcess;

function startPythonProcesses() {
  const pythonPath = 'C:/Users/Piotr/anaconda3/envs/kckpython/python.exe'; // pełna ścieżka do venv

  mediapipeProcess = spawn(pythonPath, [
    path.join(__dirname, '../python/mediapipe_service.py')
  ]);

  audioProcess = spawn(pythonPath, [
    path.join(__dirname, '../python/audio_service.py')
  ]);

  mediapipeProcess.stdout.on('data', (data) => {
    console.log(`[MediaPipe]: ${data}`);
  });

  mediapipeProcess.stderr.on('data', (data) => {
    console.error(`[MediaPipe ERROR]: ${data}`);
  });

  audioProcess.stdout.on('data', (data) => {
    console.log(`[Audio]: ${data}`);
  });

  audioProcess.stderr.on('data', (data) => {
    console.error(`[Audio ERROR]: ${data}`);
  });
}

let win;

function createWindow() {
  startPythonProcesses();

  win = new BrowserWindow({
    width: 800,
    height: 600,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  win.loadFile('index.html');

  win.webContents.once('did-finish-load', () => {
    connect();
  });
}

function connect() {
  const ws = new WebSocket('ws://localhost:8765');

  ws.on('open', () => {
    console.log('Connected');
  });

  ws.on('error', () => {
    console.log('Retrying in 2s...');
    setTimeout(connect, 2000);
  });

ws.on('message', (data) => {
    // Sprawdzamy, czy okno istnieje i czy nie zostało zniszczone
    if (win && !win.isDestroyed()) {
      const parsed = JSON.parse(data);
      win.webContents.send('mediapipe-data', parsed);
    }
  });
}

app.whenReady().then(createWindow);
// Zabijanie procesów Pythona przy wyłączaniu aplikacji
app.on('will-quit', () => {
  if (mediapipeProcess) {
    mediapipeProcess.kill();
    console.log('Proces MediaPipe zostal zakolczony.');
  }
  if (audioProcess) {
    audioProcess.kill();
    console.log('Proces Audio zostal zakolczony.');
  }
});