const { app, BrowserWindow } = require('electron');
const WebSocket = require('ws');
const { spawn } = require('child_process');
const path = require('path');


let mediapipeProcess;
let audioProcess;

function startPythonProcesses() {
  const pythonCommand = 'conda';
  const commonArgs = ['run', '-n', 'mediapipe_env', '--no-capture-output', 'python']; // pełna ścieżka do venv

  const spawnOptions = {
    shell: true,
    env: process.env
  };

  mediapipeProcess = spawn(pythonCommand, [
    ...commonArgs,
    path.join(__dirname, '../python/mediapipe_service.py'),
  ], spawnOptions);

  audioProcess = spawn(pythonCommand, [
    ...commonArgs,
    path.join(__dirname, '../python/audio_service.py')
  ], spawnOptions);

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
    const parsed = JSON.parse(data);
    win.webContents.send('mediapipe-data', parsed);
  });
}

app.whenReady().then(createWindow);

// cleanup function
// closes audio and mediapipe conda and their child python processes
// WORKS ONLY FOR WINDOWS
app.on('will-quit', () => {
  console.log('App is quitting. Cleaning up...');
  if (mediapipeProcess) {
    spawn(`taskkill /pid ${mediapipeProcess.pid} /T /F`, (err) => {
      if (err) console.log("MediaPipe already closed or error killed it.");
    });
  }

  if (audioProcess) {
    spawn(`taskkill /pid ${audioProcess.pid} /T /F`, (err) => {
      if (err) console.log("Audio already closed or error killed it.");
    });
  }
});