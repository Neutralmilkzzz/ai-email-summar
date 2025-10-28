// 全局变量
let authCredentials = null;
let eventSource = null;
let statusRefreshInterval = null;

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    initAuth();
    loadConfig();
    updateStatus();
    loadSummaryList();
    connectSSE();
    
    // 定期刷新状态
    statusRefreshInterval = setInterval(updateStatus, 5000);
    
    // 事件监听
    document.getElementById('configForm').addEventListener('submit', saveConfig);
    document.getElementById('startBtn').addEventListener('click', startTask);
    document.getElementById('stopBtn').addEventListener('click', stopTask);
    document.getElementById('refreshBtn').addEventListener('click', updateStatus);
    document.getElementById('clearLogsBtn').addEventListener('click', clearLogs);
});

// --- 认证相关 ---

function initAuth() {
    // 从 localStorage 获取保存的认证信息
    authCredentials = localStorage.getItem('auth_credentials');
    
    if (!authCredentials) {
        // 如果没有认证信息，提示用户输入
        const password = prompt('请输入管理口令:');
        if (password) {
            authCredentials = btoa(`admin:${password}`);
            localStorage.setItem('auth_credentials', authCredentials);
        } else {
            alert('需要管理口令才能使用此应用。');
            window.location.href = '/login.html';
        }
    }
}

function getAuthHeaders() {
    return {
        'Authorization': `Basic ${authCredentials}`,
        'Content-Type': 'application/json'
    };
}

// --- API 调用 ---

async function apiCall(endpoint, method = 'GET', data = null, requireAuth = true) {
    const options = {
        method: method,
        headers: requireAuth ? getAuthHeaders() : { 'Content-Type': 'application/json' }
    };
    
    if (data && method !== 'GET') {
        options.body = JSON.stringify(data);
    }
    
    try {
        const response = await fetch(endpoint, options);
        
        if (response.status === 401) {
            // 认证失败，清除保存的凭证
            localStorage.removeItem('auth_credentials');
            authCredentials = null;
            alert('认证失败，请重新输入口令。');
            initAuth();
            return null;
        }
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || `HTTP ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error(`API 调用失败 (${endpoint}):`, error);
        showAlert(`API 错误: ${error.message}`, 'error');
        return null;
    }
}

// --- 配置管理 ---

async function loadConfig() {
    const config = await apiCall('/api/config');
    if (!config) return;
    
    // 填充表单
    document.getElementById('imap_server').value = config.IMAP_SERVER || '';
    document.getElementById('imap_port').value = config.IMAP_PORT || 993;
    document.getElementById('email_account').value = config.EMAIL_ACCOUNT || '';
    document.getElementById('email_password').value = ''; // 不显示密码
    document.getElementById('deepseek_api_url').value = config.DEEPSEEK_API_URL || '';
    document.getElementById('deepseek_api_key').value = ''; // 不显示密钥
    document.getElementById('deepseek_model').value = config.DEEPSEEK_MODEL || 'deepseek-chat';
    document.getElementById('time_gap').value = config.TIME_GAP || 10;
    document.getElementById('amount_of_report').value = config.AMOUNT_OF_REPORT || 5;
    document.getElementById('smtp_server').value = config.SMTP_SERVER || '';
    document.getElementById('smtp_port').value = config.SMTP_PORT || 465;
    document.getElementById('recipient_email').value = config.RECIPIENT_EMAIL || '';
    document.getElementById('enable_smtp').checked = config.ENABLE_SMTP_NOTIFIER || false;
    document.getElementById('admin_password').value = ''; // 不显示口令
}

async function saveConfig(e) {
    e.preventDefault();
    
    const formData = new FormData(document.getElementById('configForm'));
    const data = Object.fromEntries(formData);
    
    // 处理复选框
    data.ENABLE_SMTP_NOTIFIER = document.getElementById('enable_smtp').checked;
    
    // 转换数字字段
    data.IMAP_PORT = parseInt(data.IMAP_PORT) || 993;
    data.SMTP_PORT = parseInt(data.SMTP_PORT) || 465;
    data.TIME_GAP = parseInt(data.TIME_GAP) || 10;
    data.AMOUNT_OF_REPORT = parseInt(data.AMOUNT_OF_REPORT) || 5;
    
    const result = await apiCall('/api/config', 'POST', data);
    if (result) {
        showAlert('配置已保存成功！', 'success');
        loadConfig(); // 重新加载以显示脱敏后的值
    }
}

// --- 任务控制 ---

async function startTask() {
    const result = await apiCall('/api/start', 'POST');
    if (result) {
        showAlert('任务已启动！', 'success');
        updateStatus();
    }
}

async function stopTask() {
    const result = await apiCall('/api/stop', 'POST');
    if (result) {
        showAlert('任务已停止！', 'success');
        updateStatus();
    }
}

async function updateStatus() {
    const status = await apiCall('/api/status', 'GET', null, false);
    if (!status) return;
    
    // 更新状态徽章
    const statusBadge = document.getElementById('statusBadge');
    statusBadge.textContent = status.status;
    statusBadge.className = `badge badge-${status.status.toLowerCase()}`;
    
    // 更新时间
    const lastSuccessTime = status.last_success_time ? new Date(status.last_success_time).toLocaleString('zh-CN') : '--';
    document.getElementById('lastSuccessTime').textContent = lastSuccessTime;
    
    // 更新统计
    document.getElementById('totalProcessed').textContent = status.total_processed_count || 0;
    document.getElementById('totalFailed').textContent = status.total_failed_count || 0;
    
    // 更新按钮状态
    const isRunning = status.status === 'RUNNING';
    document.getElementById('startBtn').disabled = isRunning;
    document.getElementById('stopBtn').disabled = !isRunning;
}

// --- SSE 日志流 ---

function connectSSE() {
    if (eventSource) {
        eventSource.close();
    }
    
    eventSource = new EventSource('/api/logs/stream');
    
    eventSource.onmessage = (event) => {
        try {
            const logData = JSON.parse(event.data);
            addLogEntry(logData);
        } catch (error) {
            console.error('解析日志失败:', error);
        }
    };
    
    eventSource.onerror = (error) => {
        console.error('SSE 连接错误:', error);
        eventSource.close();
        
        // 5秒后尝试重新连接
        setTimeout(connectSSE, 5000);
    };
}

function addLogEntry(logData) {
    const logContainer = document.getElementById('logContainer');
    
    // 清除初始提示
    if (logContainer.children.length === 1 && logContainer.children[0].textContent === '等待连接...') {
        logContainer.innerHTML = '';
    }
    
    // 创建日志条目
    const entry = document.createElement('div');
    entry.className = `log-entry log-${logData.level.toLowerCase()}`;
    
    // 格式化日志
    const timestamp = logData.timestamp || new Date().toLocaleTimeString('zh-CN');
    const level = logData.level || 'INFO';
    const message = logData.message || JSON.stringify(logData);
    
    entry.textContent = `[${timestamp}] ${level}: ${message}`;
    
    logContainer.appendChild(entry);
    
    // 自动滚动到底部
    logContainer.scrollTop = logContainer.scrollHeight;
    
    // 限制日志条数（最多保留 1000 条）
    while (logContainer.children.length > 1000) {
        logContainer.removeChild(logContainer.firstChild);
    }
}

function clearLogs() {
    const logContainer = document.getElementById('logContainer');
    logContainer.innerHTML = '<p class="log-entry log-info">日志已清空</p>';
}

// --- 下载管理 ---

async function loadSummaryList() {
    const list = await apiCall('/api/summaries/list', 'GET', null, false);
    if (!list) {
        document.getElementById('summaryList').innerHTML = '<p>无法加载总结列表</p>';
        return;
    }
    
    if (list.length === 0) {
        document.getElementById('summaryList').innerHTML = '<p>暂无总结文件</p>';
        return;
    }
    
    const html = list.map(file => `
        <div class="summary-item">
            <div class="summary-info">
                <div class="summary-date">📅 ${file.date}</div>
                <div class="summary-size">大小: ${formatFileSize(file.size)}</div>
            </div>
            <div class="summary-actions">
                <a href="/api/summaries/${file.date}?auth=${encodeURIComponent(authCredentials)}" download="${file.filename}">
                    ⬇️ 下载
                </a>
                <button onclick="previewSummary('${file.date}')" class="btn btn-info" style="padding: 6px 12px; font-size: 0.85em;">
                    👁️ 预览
                </button>
            </div>
        </div>
    `).join('');
    
    document.getElementById('summaryList').innerHTML = html;
}

async function previewSummary(dateStr) {
    const content = await apiCall(`/api/summaries/${dateStr}`);
    if (!content) return;
    
    // 简单的预览方式：弹出窗口
    const previewWindow = window.open('', '_blank');
    previewWindow.document.write(`
        <html>
        <head>
            <title>预览 - ${dateStr}</title>
            <style>
                body { font-family: Arial, sans-serif; padding: 20px; line-height: 1.6; }
                pre { background: #f5f5f5; padding: 15px; border-radius: 4px; overflow-x: auto; }
            </style>
        </head>
        <body>
            <h1>📧 ${dateStr} 邮件总结预览</h1>
            <pre>${escapeHtml(content)}</pre>
        </body>
        </html>
    `);
}

// --- 工具函数 ---

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

function showAlert(message, type = 'info') {
    // 简单的提示方式：使用浏览器原生 alert
    // 实际应用中可以使用自定义的提示框
    if (type === 'error') {
        console.error(message);
    } else if (type === 'success') {
        console.log(message);
    }
}

// 页面卸载时清理
window.addEventListener('beforeunload', () => {
    if (eventSource) {
        eventSource.close();
    }
    if (statusRefreshInterval) {
        clearInterval(statusRefreshInterval);
    }
});
