const { app, BrowserWindow, ipcMain, nativeTheme } = require('electron');
const WebSocket = require('ws');
const { spawn, spawnSync } = require('child_process');
const net = require('net');
const path = require('path');
const http = require('http');


let mediapipeProcess;
let audioProcess;
let mediapipePort = 8765;
let lastAudioLanguage = 'pl-PL';
let bodyNotVisibleStreak = 0;
let lastBodyNotVisibleSpokenAtMs = 0;

function getOldPythonServicePids() {
  if (process.platform !== 'win32') {
    return [];
  }

  try {
    const command = "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'audio_service_new\\.py|mediapipe_service\\.py' } | Select-Object ProcessId,CommandLine | ConvertTo-Json";
    const result = spawnSync('powershell.exe', ['-NoProfile', '-Command', command], {
      env: process.env,
      encoding: 'utf8'
    });

    if (result.status !== 0 || !result.stdout) {
      return [];
    }

    let output = result.stdout.trim();
    if (!output) {
      return [];
    }

    let parsed = JSON.parse(output);
    if (!Array.isArray(parsed)) {
      parsed = [parsed];
    }

    return parsed
      .filter((item) => item && item.ProcessId && item.CommandLine)
      .map((item) => Number(item.ProcessId));
  } catch (error) {
    console.warn('[Main] Nie udało się odczytać starych procesów Pythona:', error);
    return [];
  }
}

function cleanupOldPythonServices() {
  const pids = getOldPythonServicePids();
  if (pids.length === 0) {
    return;
  }

  console.log(`[Main] Znalazłem stare procesy Pythona: ${pids.join(', ')}`);
  for (const pid of pids) {
    try {
      spawn('taskkill', ['/PID', String(pid), '/T', '/F'], { env: process.env });
      console.log(`[Main] Zabijam stary proces Python pid=${pid}`);
    } catch (error) {
      console.warn(`[Main] Nie udało się zabić starego procesu pid=${pid}:`, error);
    }
  }
}

function waitForPort(host, port, timeoutMs = 10000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;

    const attempt = () => {
      const socket = new net.Socket();
      socket.setTimeout(500);
      socket.once('connect', () => {
        socket.destroy();
        resolve();
      });
      socket.once('timeout', () => {
        socket.destroy();
        retry();
      });
      socket.once('error', () => {
        socket.destroy();
        retry();
      });
      socket.connect(port, host);
    };

    const retry = () => {
      if (Date.now() > deadline) {
        reject(new Error(`Port ${port} did not open within ${timeoutMs}ms`));
        return;
      }
      setTimeout(attempt, 200);
    };

    attempt();
  });
}

function findPythonExecutable() {
  const candidates = [];
  if (process.env.CONDA_PREFIX) {
    candidates.push(path.join(process.env.CONDA_PREFIX, process.platform === 'win32' ? 'python.exe' : 'bin/python'));
  }
  if (process.env.VIRTUAL_ENV) {
    candidates.push(path.join(process.env.VIRTUAL_ENV, process.platform === 'win32' ? 'python.exe' : 'bin/python'));
  }
  candidates.push('python');
  candidates.push('python3');

  for (const candidate of candidates) {
    try {
      const result = spawnSync(candidate, ['--version'], { env: process.env, stdio: 'ignore' });
      if (result.status === 0) {
        console.log(`[Main] Using Python executable: ${candidate}`);
        return candidate;
      }
    } catch (error) {
      // ignore failed candidate
    }
  }

  console.warn('[Main] Nie znaleziono dostępnego Pythona; używam "python" jako fallback.');
  return 'python';
}

const pythonExecutable = findPythonExecutable();

function getAvailablePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      if (address && typeof address === 'object') {
        const port = address.port;
        server.close(() => resolve(port));
      } else {
        server.close(() => reject(new Error('Invalid address object')));
      }
    });
  });
}

async function startPythonProcesses() {
  const spawnOptions = {
    env: process.env
  };

  mediapipePort = await getAvailablePort();
  console.log(`[Main] Selected MediaPipe port: ${mediapipePort}`);

  mediapipeProcess = spawn(pythonExecutable, [
    '-u',
    path.join(__dirname, '../python/mediapipe_service.py'),
    '--port',
    String(mediapipePort),
  ], spawnOptions);

  audioProcess = spawn(pythonExecutable, [
    '-u',
    path.join(__dirname, '../python/audio_service_new.py')
  ], spawnOptions);

  mediapipeProcess.stdout.on('data', (data) => {
    const text = data.toString().trim();
    if (text) console.log(`[MediaPipe]: ${text}`);
  });

  mediapipeProcess.stderr.on('data', (data) => {
    const lines = data.toString().split('\n');
    lines.forEach(line => {
      const text = line.trim();
      if (text) {
        if (text.includes("inference_feedback_manager.cc") || text.includes("Feedback manager requires a model")) {
          return; // Ignore spam from MediaPipe C++ core
        }
        console.error(`[MediaPipe ERROR]: ${text}`);
      }
    });
  });

  audioProcess.stdout.on('data', (data) => {
    const text = data.toString().trim();
    if (text) console.log(`[Audio]: ${text}`);
  });

  audioProcess.stderr.on('data', (data) => {
    const text = data.toString().trim();
    if (text) console.error(`[Audio ERROR]: ${text}`);
  });
}

let win;

ipcMain.on('trigger-calibration', (event) => {
  if (mediapipeProcess) {
    mediapipeProcess.kill('SIGINT');
  }
});

// Zwróć obecny stan ciemnego motywu
ipcMain.handle('get-system-theme', () => nativeTheme.shouldUseDarkColors);

async function createWindow() {
  cleanupOldPythonServices();
  await startPythonProcesses();
  await waitForPort('127.0.0.1', mediapipePort, 10000);

  win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  // Reagowanie na zmiany motywu systemowego
  nativeTheme.on('updated', () => {
    if (win) {
      win.webContents.send('system-theme-updated', nativeTheme.shouldUseDarkColors);
    }
  });

  // Handle microphone permission requests
  win.webContents.session.setPermissionRequestHandler((webContents, permission, callback) => {
    if (permission === 'media') {
      callback(true);
    } else {
      callback(false);
    }
  });

  win.loadFile('index.html');

  win.webContents.once('did-finish-load', () => {
    connect();
  });
}

function connect() {
  const ws = new WebSocket(`ws://127.0.0.1:${mediapipePort}`);

  ws.on('open', () => {
    console.log('Connected');
    global.mediapipeWS = ws; // Zapamiętaj WebSocket globalnie do wysyłania config
  });

  ws.on('error', () => {
    console.log('Retrying in 2s...');
    setTimeout(connect, 2000);
  });

  ws.on('message', (data) => {
    // Sprawdzamy, czy okno istnieje i czy nie zostało zniszczone
    if (win && !win.isDestroyed()) {
      const parsed = JSON.parse(data);
      if (parsed.type === "available_cameras") {
        win.webContents.send('available-cameras', parsed.payload);
        return;
      }
      win.webContents.send('mediapipe-data', parsed);

      // Auto-voice o ustawieniu sylwetki usunięto stąd do renderer.js, by odpalać go tylko w trybie treningu.
    }
  });
}

async function speakViaAudioService(text, language) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify({ text, language });
    const options = {
      hostname: '127.0.0.1',
      port: 5000,
      path: '/speak',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload)
      },
      timeout: 5000
    };

    const req = http.request(options, (res) => {
      res.on('data', () => {});
      res.on('end', () => resolve());
    });

    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Audio Service timeout'));
    });

    req.write(payload);
    req.end();
  });
}

// =========================================================
// IPC HANDLERS - Obsługa wiadomości z renderer.js
// =========================================================

/**
 * Odbiera konfigurację z config-service.js i wysyła do Python procesów
 * 
 * Format: { "audio": {...}, "cameras": {...}, "exercise": {...} }
 */
ipcMain.handle('send-config', async (event, config) => {
  console.log('[Main IPC] Otrzymana konfiguracja z config-service.js');
  
  try {
    if (config && config.audio && typeof config.audio.language === 'string' && config.audio.language) {
      lastAudioLanguage = config.audio.language;
    }

    // 1. Wyślij do Audio Service (Flask :5000/api/config)
    const audioConfig = config.audio || {};
    if (Object.keys(audioConfig).length > 0) {
      await sendConfigToAudioService(config);
    }
    
    // 2. Wyślij do MediaPipe (WebSocket :8765)
    await sendConfigToMediaPipe(config);
    
    return { status: 'success', message: 'Konfiguracja wysłana do procesów Python' };
  } catch (error) {
    console.error('[Main IPC] Błąd:', error.message);
    return { status: 'error', message: error.message };
  }
});

/**
 * Wysyła konfigurację do Audio Service (Flask)
 */
async function sendConfigToAudioService(config) {
  return new Promise((resolve, reject) => {
    const jsonData = JSON.stringify({ config });
    
    const options = {
      hostname: '127.0.0.1',
      port: 5000,
      path: '/api/config',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(jsonData)
      },
      timeout: 5000
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        console.log(`[Main] Audio Service POST /api/config: ${res.statusCode}`);
        resolve();
      });
    });

    req.on('error', (error) => {
      console.warn(`[Main] Błąd wysyłania do Audio Service: ${error.message}`);
      resolve(); // Nie przerywaj jeśli audio service niedostępny
    });

    req.on('timeout', () => {
      req.destroy();
      console.warn('[Main] Audio Service timeout');
      resolve();
    });

    req.write(jsonData);
    req.end();
  });
}

/**
 * Wysyła konfigurację do MediaPipe (WebSocket)
 */
async function sendConfigToMediaPipe(config) {
  // Przechowuj globalny WebSocket do MediaPipe
  if (!global.mediapipeWS || global.mediapipeWS.readyState !== WebSocket.OPEN) {
    console.warn('[Main] MediaPipe WebSocket nie jest otwarty');
    return;
  }

  const message = {
    type: 'config',
    payload: config
  };

  try {
    global.mediapipeWS.send(JSON.stringify(message));
    console.log('[Main] Konfiguracja wysłana do MediaPipe');
  } catch (error) {
    console.error('[Main] Błąd wysyłania do MediaPipe:', error.message);
  }
}

app.whenReady().then(createWindow);

function terminatePythonProcess(child, label) {
  if (!child || child.killed) {
    return;
  }

  try {
    child.kill();
    console.log(`[Main] Sent termination signal to ${label} process (pid=${child.pid}).`);
  } catch (error) {
    console.error(`[Main] Failed to kill ${label} process:`, error);
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { env: process.env });
    }
  }
}

function cleanupPythonProcesses() {
  console.log('[Main] Cleaning up Python child processes...');
  terminatePythonProcess(mediapipeProcess, 'MediaPipe');
  terminatePythonProcess(audioProcess, 'Audio');
}

app.on('before-quit', cleanupPythonProcesses);
app.on('will-quit', cleanupPythonProcesses);
app.on('quit', cleanupPythonProcesses);
process.on('exit', cleanupPythonProcesses);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    cleanupPythonProcesses();
    app.quit();
  }
});