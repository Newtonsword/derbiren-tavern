// 小魔王地下城 · Electron 主进程
const { app, BrowserWindow, Menu } = require('electron');
const path = require('path');

function createWindow() {
  const win = new BrowserWindow({
    width: 1000,
    height: 750,
    minWidth: 360,
    minHeight: 540,
    title: '小魔王地下城',
    backgroundColor: '#1a1410',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  // 加载 web/index.html（纯静态，无需服务器）
  win.loadFile(path.join(__dirname, '..', 'web', 'index.html'));
  return win;
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});