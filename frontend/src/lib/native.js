// pywebview 窗口里才有原生对话框（app.py 的 NativeApi）；浏览器调试时没有，界面退回手输路径。
const api = () => window.pywebview?.api

export const hasNative = () => typeof api()?.pick_folder === 'function'

export async function pickFolder() {
  return (await api().pick_folder()) || null
}

export async function pickFiles() {
  return (await api().pick_files()) || []
}
