// config.js - 配置管理器
class ConfigManager {
    constructor() {
        this.config = null;
        this.isLoaded = false;
        this.loadPromise = null;
    }
    
    async loadConfig() {
        // 如果已经在加载中，返回相同的Promise
        if (this.loadPromise) {
            return this.loadPromise;
        }
        
        this.loadPromise = this._doLoadConfig();
        return this.loadPromise;
    }
    
    async _doLoadConfig() {
        try {
            console.log('📋 Starting to load config file...');
            // 加时间戳并禁止缓存，防止线上仍读到旧配置
            const response = await fetch(`./config.json?t=${Date.now()}`, { cache: 'no-store' });
            
            if (!response.ok) {
                throw new Error(`Config file load failed: HTTP ${response.status} ${response.statusText}`);
            }
            
            this.config = await response.json();
            this.isLoaded = true;
            
            // 验证配置完整性
            this._validateConfig();
            
            console.log('✅ Config file loaded successfully:', this.config);
            return this.config;
        } catch (error) {
            this.config = null;
            this.isLoaded = false;
            console.error('❌ Config file load failed:', error);
            
            // Show user-friendly error message
            this._showConfigError(error.message);
            throw new Error(`Config load failed: ${error.message}`);
        }
    }
    
    _validateConfig() {
        if (!this.config) {
            throw new Error('Config object is empty');
        }
        
        if (!this.config.backend) {
            throw new Error('Config file missing backend configuration');
        }
        
        const { host, port, protocol, wsProtocol } = this.config.backend;
        
        if (!host) {
            throw new Error('Config file missing backend.host');
        }
        
        if (!port) {
            throw new Error('Config file missing backend.port');
        }
        
        if (!protocol) {
            throw new Error('Config file missing backend.protocol');
        }
        
        if (!wsProtocol) {
            throw new Error('Config file missing backend.wsProtocol');
        }
        
        console.log('✅ Config file validation passed');
    }
    
    _showConfigError(message) {
        // 创建错误提示界面
        const errorHtml = `
            <div style="
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0,0,0,0.8);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10000;
                color: white;
                font-family: Arial, sans-serif;
            ">
                <div style="
                    background: #f56565;
                    padding: 30px;
                    border-radius: 10px;
                    max-width: 500px;
                    text-align: center;
                ">
                    <h2>⚠️ 配置文件加载失败</h2>
                    <p>无法加载配置文件 <code>config.json</code>。请检查：</p>
                    <ul>
                        <li>确保前端目录中存在 <code>config.json</code> 文件</li>
                        <li>检查文件格式是否为正确的JSON</li>
                        <li>验证后端服务是否正在运行</li>
                        <li>检查网络连接</li>
                    </ul>
                    <p><strong>错误详情：</strong> ${message}</p>
                    <p>请修复上述问题后刷新页面。</p>
                    <button onclick="window.location.reload()" style="
                        background: white;
                        color: #f56565;
                        border: none;
                        padding: 10px 20px;
                        border-radius: 5px;
                        cursor: pointer;
                        font-weight: bold;
                        margin-top: 15px;
                    ">Reload</button>
                </div>
            </div>
        `;
        
        // 添加到页面
        const errorDiv = document.createElement('div');
        errorDiv.innerHTML = errorHtml;
        document.body.appendChild(errorDiv);
    }
    
    // 确保配置已加载的检查方法
    _ensureConfigLoaded() {
        if (!this.isLoaded || !this.config) {
            throw new Error('Config file not loaded, please call loadConfig() method first');
        }
    }
    
    getApiBaseUrl() {
        this._ensureConfigLoaded();
        // 线上优先使用“当前页面域名 + 配置端口”，避免 host 配错
        if (!this.isLocalDeployment()) {
            const currentProto = window.location.protocol === 'https:' ? 'https' : 'http';
            const currentHost = window.location.hostname;
            const { port } = this.config.backend;
            return `${currentProto}://${currentHost}:${port}`;
        }
        // 本地保留原规则
        if (this.config.api && this.config.api.baseUrl) {
            return this.config.api.baseUrl;
        }
        const { protocol, host, port } = this.config.backend;
        return `${protocol}://${host}:${port}`;
    }
    
    getWebSocketUrl() {
        this._ensureConfigLoaded();
        
        // 优先使用 api.wsUrl，否则构建地址
        if (this.config.api && this.config.api.wsUrl) {
            return this.config.api.wsUrl;
        }
        
        const { wsProtocol, host, port } = this.config.backend;
        return `${wsProtocol}://${host}:${port}`;
    }
    
    getFullApiUrl(endpoint) {
        const baseUrl = this.getApiBaseUrl();
        return `${baseUrl}${endpoint.startsWith('/') ? endpoint : '/' + endpoint}`;
    }
    
    getFullWebSocketUrl(endpoint) {
        const wsUrl = this.getWebSocketUrl();
        return `${wsUrl}${endpoint.startsWith('/') ? endpoint : '/' + endpoint}`;
    }
    
    // 检查当前页面host是否与配置host一致
    isLocalDeployment() {
        this._ensureConfigLoaded();
        
        const currentHost = window.location.hostname;
        const configHost = this.config.backend.host;
        
        // 如果配置的host是localhost或127.0.0.1，且当前也是，认为是本地部署
        const localhostAliases = ['localhost', '127.0.0.1', '::1'];
        const currentIsLocal = localhostAliases.includes(currentHost);
        const configIsLocal = localhostAliases.includes(configHost);
        
        return currentIsLocal && configIsLocal;
    }
    
    // 智能获取WebSocket URL（考虑跨域情况）
    getSmartWebSocketUrl(endpoint = '/ws/chat') {
        this._ensureConfigLoaded();
        
        // 如果是本地部署，使用配置的地址
        if (this.isLocalDeployment()) {
            return this.getFullWebSocketUrl(endpoint);
        }
        
        // 如果是跨域部署，使用当前页面的host但配置的端口
        const currentProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const currentHost = window.location.hostname;
        const configPort = this.config.backend.port;
        
        return `${currentProtocol}://${currentHost}:${configPort}${endpoint}`;
    }
}

// 创建全局配置管理器实例
window.configManager = new ConfigManager();

// 立即开始加载配置
window.configManager.loadConfig().catch(error => {
    console.error('❌ 配置加载失败，应用无法正常工作:', error);
});