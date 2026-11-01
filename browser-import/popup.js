const button = document.getElementById('import');
const state = document.getElementById('state');
button.addEventListener('click', async () => {
  button.disabled = true;
  state.textContent = '正在读取B站会话并验证…';
  try {
    const pairingResponse = await fetch(chrome.runtime.getURL('pairing.local.json'));
    if (!pairingResponse.ok) throw new Error('导入入口未启动，请重新运行登录导入脚本，并加载其输出的扩展目录。');
    const pairing = await pairingResponse.json();
    const cookies = await chrome.cookies.getAll({ domain: 'bilibili.com' });
    if (!cookies.some(cookie => cookie.name === 'SESSDATA')) throw new Error('此浏览器配置没有B站登录态，请先登录。');
    const response = await fetch('http://127.0.0.1:17890/session/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Bilibili-Pair': pairing.token },
      body: JSON.stringify({ cookies })
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || '会话导入失败');
    state.textContent = `已绑定：${result.account.name}（UID ${result.account.mid}）\n凭证只保存在本机；MCP现在可直接使用。`;
  } catch (error) {
    state.textContent = String(error.message || error);
    button.disabled = false;
  }
});
